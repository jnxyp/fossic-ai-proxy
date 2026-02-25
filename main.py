from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config import AppConfig, TenantConfig, load_config
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
    tenant_count = len({t.name for t in app_config.tenants.values()})
    log.info(f"loaded {tenant_count} tenant(s), {len(app_config.upstreams)} upstream(s)")
    yield


app = FastAPI(title="fossic-ai-proxy", lifespan=lifespan)


def get_tenant(credentials: HTTPAuthorizationCredentials = Depends(bearer)) -> TenantConfig:
    tenant = app_config.tenants.get(credentials.credentials)
    if tenant is None:
        raise HTTPException(status_code=401, detail="Invalid API key.")
    return tenant


def _cors_headers(origin: str, tenant: TenantConfig) -> dict:
    if origin and origin in tenant.cors_origins:
        return {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
        }
    return {}


@app.options("/v1/chat/completions")
async def chat_completions_preflight(request: Request):
    origin = request.headers.get("origin", "")
    allowed = any(origin in t.cors_origins for t in app_config.tenants.values())
    if allowed:
        return Response(status_code=204, headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Authorization, Content-Type",
            "Access-Control-Max-Age": "86400",
        })
    return Response(status_code=403)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, tenant: TenantConfig = Depends(get_tenant)):
    if tenant.allowed_referers:
        referer = request.headers.get("referer", "")
        if not any(referer.startswith(r) for r in tenant.allowed_referers):
            log.warning(f"[{tenant.name}] blocked: referer='{referer}'")
            raise HTTPException(status_code=403, detail="Referer not allowed.")

    body = await request.json()

    try:
        modified_body = inject(body, tenant)
    except HTTPException as e:
        log.warning(f"[{tenant.name}] rejected: {e.detail}")
        raise

    model = modified_body.get("model", "?")
    user_msgs = [m for m in body.get("messages", []) if m.get("role") == "user"]
    total_chars = sum(len(m.get("content", "")) for m in body.get("messages", []) if isinstance(m.get("content"), str))
    stream = modified_body.get("stream", False)

    log.info(f"[{tenant.name}] -> {tenant.upstream_id}/{model} | msgs={len(user_msgs)} chars={total_chars} stream={stream}")

    t0 = time.monotonic()
    response = await forward(modified_body, tenant)
    elapsed = time.monotonic() - t0

    log.info(f"[{tenant.name}] <- {tenant.upstream_id}/{model} | {elapsed:.2f}s")

    origin = request.headers.get("origin", "")
    for k, v in _cors_headers(origin, tenant).items():
        response.headers[k] = v

    return response
