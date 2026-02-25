from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import db
from config import AppConfig, TenantConfig, load_config
from injector import inject
from logger import get_logger, set_level
from proxy import forward, _parse_sse_content

log = get_logger()

app_config: AppConfig | None = None
bearer = HTTPBearer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global app_config
    db.init_db()
    app_config = load_config("config.yaml")
    set_level(app_config.log_level)
    tenant_count = len({t.name for t in app_config.tenants.values()})
    log.info(f"loaded {tenant_count} tenant(s), {len(app_config.agents)} agent(s), "
             f"{len(app_config.upstreams)} upstream(s), log_level={app_config.log_level.upper()}")
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
    used_key = request.headers.get("authorization", "").removeprefix("Bearer ").strip()

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
    input_chars = sum(len(m.get("content", "")) for m in body.get("messages", []) if isinstance(m.get("content"), str))
    is_stream = modified_body.get("stream", False)

    log.info(f"[{tenant.name}] -> {tenant.agent_id}/{model} | msgs={len(user_msgs)} chars={input_chars} stream={is_stream}")
    log.debug(f"[{tenant.name}] received body")
    log.debug(json.dumps(body, ensure_ascii=False))
    log.debug(f"[{tenant.name}] injected body")
    log.debug(json.dumps(modified_body, ensure_ascii=False))

    t0 = time.monotonic()
    response = await forward(modified_body, tenant)
    elapsed = time.monotonic() - t0

    log.info(f"[{tenant.name}] <- {tenant.agent_id}/{model} | {elapsed:.2f}s")

    origin = request.headers.get("origin", "")
    cors = _cors_headers(origin, tenant)

    if isinstance(response, StreamingResponse):
        original_iter = response.body_iterator

        async def counting_stream():
            output_chars = 0
            stream_start = time.monotonic()
            try:
                async for chunk in original_iter:
                    if isinstance(chunk, bytes):
                        output_chars += len(_parse_sse_content(chunk))
                    yield chunk
            finally:
                elapsed_ms = int((time.monotonic() - stream_start) * 1000)
                asyncio.create_task(asyncio.to_thread(
                    db.log_request, tenant.name, used_key, model,
                    True, input_chars, output_chars, elapsed_ms, 200,
                ))

        response = StreamingResponse(counting_stream(), media_type="text/event-stream")
    else:
        # Non-streaming: parse output chars from response body
        try:
            data = json.loads(response.body)
            content = (data.get("choices", [{}])[0].get("message", {}).get("content") or "")
            output_chars = len(content) if isinstance(content, str) else 0
        except Exception:
            output_chars = None
        elapsed_ms = int(elapsed * 1000)
        asyncio.create_task(asyncio.to_thread(
            db.log_request, tenant.name, used_key, model,
            False, input_chars, output_chars, elapsed_ms, 200,
        ))

    for k, v in cors.items():
        response.headers[k] = v

    return response
