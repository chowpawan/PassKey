from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import init_db
from app.routes import vault, webauthn


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="PassKey", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.expected_origin],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(webauthn.router, prefix="/api/webauthn", tags=["webauthn"])
    app.include_router(vault.router, prefix="/api/vault", tags=["vault"])

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
