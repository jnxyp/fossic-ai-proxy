from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import AppConfig, UserConfig, load_config
from injector import inject
from proxy import forward

app_config: AppConfig | None = None
bearer = HTTPBearer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_config
    app_config = load_config("config.yaml")
    print(f"[startup] loaded {len(app_config.users)} user(s), {len(app_config.upstreams)} upstream(s)")
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
    # 预检请求无法鉴权，匹配任意用户的 cors_origins
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
            raise HTTPException(status_code=403, detail="Referer not allowed.")

    body = await request.json()
    modified_body = inject(body, user)
    response = await forward(modified_body, user)

    origin = request.headers.get("origin", "")
    for k, v in _cors_headers(origin, user).items():
        response.headers[k] = v

    return response
