from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import AppConfig, UserConfig, load_config
from injector import inject
from proxy import forward

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("fossic-ai-proxy")

app_config: AppConfig | None = None
bearer = HTTPBearer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_config
    app_config = load_config("config.yaml")
    log.info(f"loaded {len(app_config.users)} user(s), {len(app_config.upstreams)} upstream(s)")
    yield


app = FastAPI(title="fossic-ai-proxy", lifespan=lifespan)


def get_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> UserConfig:
    user = app_config.users.get(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return user


def _cors_headers(origin: str, user: UserConfig) -> dict:
    if origin and origin in user.cors_origins:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
        }
    return {}


@app.options("/v1/chat/completions")
async def chat_completions_preflight(request: Request):
    origin = request.headers.get("origin", "")
    allowed = any(origin in user.cors_origins for user in app_config.users.values())
    if allowed:
        return Response(status_code=204, headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Max-Age": "86400",
        })
    return Response(status_code=403)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, user: UserConfig = Depends(get_user)):
    if user.allowed_referers:
        referer = request.headers.get("referer", "")
        if not any(referer.startswith(r) for r in user.allowed_referers):
            log.warning(f"[{user.name}] blocked: referer='{referer}'")
            raise HTTPException(status_code=403, detail="Referer not allowed.")

    body = await request.json()

    try:
        modified_body = inject(body, user)
    except HTTPException as e:
        log.warning(f"[{user.name}] rejected: {e.detail}")
        raise

    model = modified_body.get("model", "?")
    user_msgs = [m for m in body.get("messages", []) if m.get("role") == "user"]
    total_chars = sum(len(m.get("content", "")) for m in body.get("messages", []) if isinstance(m.get("content"), str))
    stream = modified_body.get("stream", False)

    log.info(f"[{user.name}] -> {user.upstream_id}/{model} | msgs={len(user_msgs)} chars={total_chars} stream={stream}")

    t0 = time.monotonic()
    response = await forward(modified_body, user)
    elapsed = time.monotonic() - t0

    log.info(f"[{user.name}] <- {user.upstream_id}/{model} | {elapsed:.2f}s")

    origin = request.headers.get("origin", "")
    for k, v in _cors_headers(origin, user).items():
        response.headers[k] = v

    return response
