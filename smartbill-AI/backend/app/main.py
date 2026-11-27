from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import load_backend_environment

load_backend_environment()

from app.auth import auth_configuration_status, require_owner
from app.database import (
    DATABASE_PATH,
    DEFAULT_ENGINE,
    engine,
    initialize_database,
    verify_database_schema,
)
from app.rate_limit import limit_business_api
from app.routers import (
    assistant,
    auth,
    categories,
    customers,
    invoices,
    products,
    reports,
)

logger = logging.getLogger(__name__)
is_production = (
    os.environ.get("SMARTBILL_ENV", "development").strip().lower()
    == "production"
)


def _csv_setting(name: str, default: str = "") -> list[str]:
    return [
        value.strip()
        for value in os.environ.get(name, default).split(",")
        if value.strip()
    ]


def _validate_production_configuration() -> list[str]:
    if not os.environ.get("SMARTBILL_DATABASE_PATH", "").strip():
        raise RuntimeError(
            "SMARTBILL_DATABASE_PATH must point to a persistent database volume."
        )
    if not os.environ.get("SMARTBILL_RAG_DB_PATH", "").strip():
        raise RuntimeError(
            "SMARTBILL_RAG_DB_PATH must point to a persistent RAG database volume."
        )
    database_path = Path(
        os.environ["SMARTBILL_DATABASE_PATH"]
    ).expanduser().resolve()
    rag_database_path = Path(os.environ["SMARTBILL_RAG_DB_PATH"]).expanduser().resolve()
    if database_path == rag_database_path:
        raise RuntimeError("The billing and RAG databases must be separate files.")
    if not rag_database_path.parent.is_dir():
        raise RuntimeError(
            "Provision the persistent directory for SMARTBILL_RAG_DB_PATH before startup."
        )
    if not auth_configuration_status():
        raise RuntimeError(
            "Production owner authentication must use a password hash, "
            "username, and session secret."
        )
    if os.environ.get("SMARTBILL_COOKIE_SECURE", "").strip().lower() != "true":
        raise RuntimeError("Set SMARTBILL_COOKIE_SECURE=true in production.")

    origins = _csv_setting("SMARTBILL_CORS_ORIGINS")
    parsed_origins = [urlsplit(origin) for origin in origins]
    if not origins or any(
        origin == "*"
        or parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path
        or parsed.query
        or parsed.fragment
        for origin, parsed in zip(origins, parsed_origins, strict=True)
    ):
        raise RuntimeError(
            "Production CORS origins must be explicit HTTPS frontend origins."
        )

    trusted_hosts = _csv_setting("SMARTBILL_TRUSTED_HOSTS")
    if not trusted_hosts or "*" in trusted_hosts:
        raise RuntimeError(
            "Set SMARTBILL_TRUSTED_HOSTS to explicit API host names."
        )
    return trusted_hosts


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    if is_production:
        _validate_production_configuration()
        verify_database_schema(engine)
    elif engine is DEFAULT_ENGINE and DATABASE_PATH.is_file():
        verify_database_schema(engine)
    else:
        initialize_database(engine)
    yield


app = FastAPI(
    title="SmartBill AI",
    description="Retail product, billing, customer, and sales management API.",
    version="0.1.0",
    lifespan=lifespan,
)

cors_origins = [
    *_csv_setting(
        "SMARTBILL_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Idempotency-Key", "X-CSRF-Token"],
    allow_credentials=True,
)
if is_production:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=_csv_setting("SMARTBILL_TRUSTED_HOSTS"),
    )


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if is_production and request.url.scheme == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000"
        )
    return response


@app.exception_handler(SQLAlchemyError)
async def handle_database_error(
    _request: Request, error: SQLAlchemyError
) -> JSONResponse:
    logger.error("Database request failed (%s).", type(error).__name__)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "The database operation failed. No changes were saved."},
    )


app.include_router(auth.router)
protected = [Depends(require_owner), Depends(limit_business_api)]
app.include_router(products.router, dependencies=protected)
app.include_router(categories.router, dependencies=protected)
app.include_router(customers.router, dependencies=protected)
app.include_router(invoices.router, dependencies=protected)
app.include_router(reports.router, dependencies=protected)
app.include_router(assistant.router, dependencies=protected)


@app.get("/", tags=["General"])
async def read_root() -> dict[str, str]:
    return {"message": "Welcome to SmartBill AI API"}


@app.get("/health", tags=["Health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/ready",
    tags=["Health"],
    summary="Check database readiness",
    responses={503: {"description": "The database is unavailable."}},
)
def readiness_check() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        logger.error("Database readiness check failed (%s).", type(error).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The database is unavailable.",
        ) from error
    return {"status": "ready"}
