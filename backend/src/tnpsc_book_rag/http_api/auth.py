"""Managed OIDC authentication and route-level authorization dependencies."""

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Protocol

import jwt
from fastapi import Depends, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.http_api.errors import ApiProblem


class ApiScope(StrEnum):
    """Stable permissions understood by the API."""

    RAG_QUERY = "rag:query"
    CATALOG_WRITE = "catalog:write"
    INGESTION_READ = "ingestion:read"
    INSPECTION_READ = "inspection:read"
    INSPECTION_WRITE = "inspection:write"


_ALL_SCOPES = frozenset(ApiScope)
_ALL_SCOPE_VALUES = frozenset(scope.value for scope in ApiScope)
_ROLE_SCOPES: Mapping[str, frozenset[ApiScope]] = {
    "reader": frozenset({ApiScope.RAG_QUERY}),
    "curator": frozenset(
        {
            ApiScope.RAG_QUERY,
            ApiScope.CATALOG_WRITE,
            ApiScope.INGESTION_READ,
        }
    ),
    "admin": _ALL_SCOPES,
}
_BEARER = HTTPBearer(
    auto_error=False,
    bearerFormat="JWT",
    description="Short-lived access token issued by the configured OpenID Connect provider.",
)


@dataclass(frozen=True, slots=True)
class Principal:
    """Authenticated API identity without profile or other personal claims."""

    subject: str
    roles: frozenset[str]
    scopes: frozenset[ApiScope]


class TokenVerifier(Protocol):
    """Decode and validate one externally issued access token."""

    async def verify(self, token: str) -> Mapping[str, Any]: ...


class OidcJwtVerifier:
    """Validate asymmetric JWT access tokens against a cached JWKS endpoint."""

    def __init__(self, settings: Settings) -> None:
        if (
            settings.oidc_jwks_url is None
            or settings.oidc_issuer is None
            or settings.oidc_audience is None
        ):
            msg = "OIDC verifier requires complete validated settings"
            raise ValueError(msg)
        self._client = jwt.PyJWKClient(
            str(settings.oidc_jwks_url),
            cache_jwk_set=True,
            cache_keys=True,
            lifespan=300,
        )
        self._issuer = str(settings.oidc_issuer)
        self._audience = settings.oidc_audience
        self._algorithms = list(settings.oidc_algorithms)

    async def verify(self, token: str) -> Mapping[str, Any]:
        signing_key = await asyncio.to_thread(self._client.get_signing_key_from_jwt, token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=self._algorithms,
            audience=self._audience,
            issuer=self._issuer,
            options={"require": ["exp", "sub"]},
        )


class AuthenticationService:
    """Authenticate bearer tokens and translate external roles into API scopes."""

    def __init__(
        self,
        *,
        enabled: bool,
        verifier: TokenVerifier | None = None,
        roles_claim: str = "roles",
        scopes_claim: str = "scope",
    ) -> None:
        if enabled and verifier is None:
            msg = "enabled authentication requires a token verifier"
            raise ValueError(msg)
        self.enabled = enabled
        self._verifier = verifier
        self._roles_claim = roles_claim
        self._scopes_claim = scopes_claim

    async def authenticate(self, token: str | None) -> Principal:
        if not self.enabled:
            return Principal(
                subject="development",
                roles=frozenset({"admin"}),
                scopes=_ALL_SCOPES,
            )
        if token is None:
            raise _authentication_problem("A bearer access token is required.")
        if self._verifier is None:
            msg = "enabled authentication has no token verifier"
            raise RuntimeError(msg)
        try:
            claims = await self._verifier.verify(token)
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject.strip() or len(subject) > 512:
                raise ValueError
            roles = frozenset(value.lower() for value in _claim_values(claims, self._roles_claim))
            direct_scopes = {
                ApiScope(value)
                for value in _claim_values(claims, self._scopes_claim)
                if value in _ALL_SCOPE_VALUES
            }
        except (jwt.PyJWTError, TypeError, ValueError):
            raise _authentication_problem(
                "The bearer access token is invalid or expired."
            ) from None

        role_scopes = set[ApiScope]()
        for role in roles:
            role_scopes.update(_ROLE_SCOPES.get(role, ()))
        return Principal(
            subject=subject,
            roles=roles,
            scopes=frozenset(role_scopes | direct_scopes),
        )


def create_authentication_service(settings: Settings) -> AuthenticationService:
    """Create the configured fail-closed authentication boundary."""
    verifier = OidcJwtVerifier(settings) if settings.auth_enabled else None
    return AuthenticationService(
        enabled=settings.auth_enabled,
        verifier=verifier,
        roles_claim=settings.oidc_roles_claim,
        scopes_claim=settings.oidc_scopes_claim,
    )


def _claim_values(claims: Mapping[str, Any], name: str) -> tuple[str, ...]:
    raw = claims.get(name, ())
    if isinstance(raw, str):
        return tuple(raw.split())
    if isinstance(raw, Sequence) and not isinstance(raw, (bytes, bytearray)):
        values = tuple(raw)
        if all(isinstance(value, str) for value in values):
            return values
    raise ValueError


def _authentication_problem(detail: str) -> ApiProblem:
    return ApiProblem(
        status=401,
        code="authentication_required",
        title="Authentication required",
        detail=detail,
        headers=(("WWW-Authenticate", "Bearer"),),
    )


async def current_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(_BEARER)],
) -> Principal:
    """Resolve and cache the current request principal."""
    authentication: AuthenticationService = request.app.state.authentication
    token = credentials.credentials if credentials is not None else None
    principal = await authentication.authenticate(token)
    request.state.principal = principal
    return principal


def require_scopes(
    *required_scopes: ApiScope,
) -> Any:
    """Return a FastAPI dependency requiring every requested API scope."""

    async def authorize(
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> Principal:
        missing = frozenset(required_scopes) - principal.scopes
        if missing:
            raise ApiProblem(
                status=403,
                code="insufficient_scope",
                title="Insufficient permission",
                detail="The authenticated identity cannot perform this operation.",
            )
        return principal

    return authorize


__all__ = [
    "ApiScope",
    "AuthenticationService",
    "OidcJwtVerifier",
    "Principal",
    "TokenVerifier",
    "create_authentication_service",
    "current_principal",
    "require_scopes",
]
