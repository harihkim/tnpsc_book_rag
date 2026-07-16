"""Safe Problem Details responses for versioned API routes."""

from dataclasses import dataclass, field

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from tnpsc_book_rag.observability import get_correlation_context


@dataclass(frozen=True, slots=True)
class ValidationFieldError:
    """One stable field-specific validation failure."""

    field: str
    message: str
    code: str


@dataclass(frozen=True, slots=True)
class ApiProblem(Exception):
    """Expected safe error that a versioned route may expose."""

    status: int
    code: str
    title: str
    detail: str
    errors: tuple[ValidationFieldError, ...] = field(default_factory=tuple)


def _request_id() -> str:
    return get_correlation_context().get("request_id", "unavailable")


def problem_response(request: Request, problem: ApiProblem) -> JSONResponse:
    """Serialize a bounded application error using the frozen v1 shape."""
    return JSONResponse(
        {
            "type": f"urn:tnpsc-book-rag:problem:{problem.code.replace('_', '-')}",
            "title": problem.title,
            "status": problem.status,
            "detail": problem.detail,
            "instance": request.url.path,
            "code": problem.code,
            "request_id": _request_id(),
            "errors": [
                {"field": error.field, "message": error.message, "code": error.code}
                for error in problem.errors
            ],
        },
        status_code=problem.status,
        media_type="application/problem+json",
    )


def _validation_errors(error: RequestValidationError) -> tuple[ValidationFieldError, ...]:
    result: list[ValidationFieldError] = []
    for item in error.errors():
        location = ".".join(str(part) for part in item.get("loc", ()))
        result.append(
            ValidationFieldError(
                field=location or "request",
                message=str(item.get("msg", "Invalid value.")),
                code=str(item.get("type", "invalid")),
            )
        )
    return tuple(result)


def install_exception_handlers(application: FastAPI) -> None:
    """Install versioned error mappings shared by every implemented API route."""

    @application.exception_handler(ApiProblem)
    async def handle_api_problem(request: Request, error: ApiProblem) -> JSONResponse:
        return problem_response(request, error)

    @application.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, error: RequestValidationError) -> JSONResponse:
        if not request.url.path.startswith("/v1/"):
            return JSONResponse({"detail": error.errors()}, status_code=422)
        return problem_response(
            request,
            ApiProblem(
                status=422,
                code="validation_error",
                title="Validation failed",
                detail="One or more request fields are invalid.",
                errors=_validation_errors(error),
            ),
        )

    @application.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, _: SQLAlchemyError) -> JSONResponse:
        return problem_response(
            request,
            ApiProblem(
                status=503,
                code="database_unavailable",
                title="Database unavailable",
                detail="The textbook catalog is temporarily unavailable.",
            ),
        )
