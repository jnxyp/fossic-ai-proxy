from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
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


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, user: UserConfig = Depends(get_user)):
    body = await request.json()
    modified_body = inject(body, user)
    return await forward(modified_body, user)
