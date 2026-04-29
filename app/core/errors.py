from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _envelope(code: str, message: str, request_id: str | None, details: object | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "error": {"code": code, "message": message},
    }
    if request_id:
        payload["request_id"] = request_id
    if details is not None:
        payload["error"]["details"] = details  # type: ignore[index]
    return payload


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(
                code=f"http_{exc.status_code}",
                message=str(exc.detail),
                request_id=_request_id(request),
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Pydantic v2 stuffs the original exception into the error's ``ctx``
        # field; jsonable_encoder coerces those non-JSON values to strings.
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=jsonable_encoder(
                _envelope(
                    code="validation_error",
                    message="request payload failed validation",
                    request_id=_request_id(request),
                    details=exc.errors(),
                )
            ),
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        logger.warning("integrity_error", extra={"extra": {"error": str(exc.orig)}})
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=_envelope(
                code="conflict",
                message="resource conflict",
                request_id=_request_id(request),
            ),
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("database_error")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=_envelope(
                code="database_unavailable",
                message="database operation failed",
                request_id=_request_id(request),
            ),
        )

    @app.exception_handler(Exception)
    async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unexpected_error")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope(
                code="internal_error",
                message="unexpected server error",
                request_id=_request_id(request),
            ),
        )
