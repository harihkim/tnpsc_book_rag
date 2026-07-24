"""Authentication, authorization, and request-admission boundary tests."""

from collections.abc import Mapping
from typing import Any, override

import jwt
import pytest
from fastapi import Depends, FastAPI
from httpx2 import ASGITransport, AsyncClient

from tnpsc_book_rag.http_api.auth import (
    ApiScope,
    AuthenticationService,
    require_scopes,
)
from tnpsc_book_rag.http_api.errors import install_exception_handlers
from tnpsc_book_rag.http_api.rate_limits import (
    ANSWER_GLOBAL_CONCURRENCY,
    SEARCH_MINUTE,
    ConcurrencyPolicy,
    DisabledRateLimiter,
    RateDecision,
    RatePolicy,
    enforce_authenticated_rate,
    enforce_concurrency,
)


class StaticVerifier:
    """Return fixed validated claims or a fixed JWT failure."""

    def __init__(
        self,
        claims: Mapping[str, Any] | None = None,
        *,
        invalid: bool = False,
    ) -> None:
        self._claims = claims or {}
        self._invalid = invalid

    async def verify(self, token: str) -> Mapping[str, Any]:
        del token
        if self._invalid:
            raise jwt.InvalidTokenError
        return self._claims


class ControllableLimiter(DisabledRateLimiter):
    """Record admission calls and return controllable decisions."""

    def __init__(
        self,
        *,
        rate_decision: RateDecision | None = None,
        concurrency_decision: RateDecision | None = None,
    ) -> None:
        self.rate_decision = rate_decision or RateDecision(True, 0)
        self.concurrency_decision = concurrency_decision or RateDecision(True, 0)
        self.rate_calls: list[tuple[str, str]] = []
        self.acquired: list[tuple[str, str, str]] = []
        self.released: list[tuple[str, str, str]] = []

    @override
    def subject_key(self, subject: str) -> str:
        return f"subject-key:{subject}"

    @override
    async def check_rate(self, policy: RatePolicy, identity: str) -> RateDecision:
        self.rate_calls.append((policy.name, identity))
        return self.rate_decision

    @override
    async def acquire_concurrency(
        self,
        policy: ConcurrencyPolicy,
        identity: str,
        token: str,
    ) -> RateDecision:
        self.acquired.append((policy.name, identity, token))
        return self.concurrency_decision

    @override
    async def release_concurrency(
        self,
        policy: ConcurrencyPolicy,
        identity: str,
        token: str,
    ) -> None:
        self.released.append((policy.name, identity, token))


def _application(
    authentication: AuthenticationService,
    limiter: DisabledRateLimiter | ControllableLimiter | None = None,
) -> FastAPI:
    application = FastAPI()
    application.state.authentication = authentication
    application.state.rate_limiter = limiter or DisabledRateLimiter()
    install_exception_handlers(application)

    @application.get(
        "/rag",
        dependencies=[
            Depends(require_scopes(ApiScope.RAG_QUERY)),
            Depends(enforce_authenticated_rate(SEARCH_MINUTE)),
        ],
    )
    async def rag() -> dict[str, bool]:
        return {"ok": True}

    @application.get(
        "/admin",
        dependencies=[Depends(require_scopes(ApiScope.INSPECTION_WRITE))],
    )
    async def admin() -> dict[str, bool]:
        return {"ok": True}

    @application.get(
        "/capacity",
        dependencies=[Depends(enforce_concurrency(ANSWER_GLOBAL_CONCURRENCY))],
    )
    async def capacity() -> dict[str, bool]:
        return {"ok": True}

    return application


@pytest.mark.anyio
async def test_reader_role_maps_to_query_scope_without_admin_access() -> None:
    authentication = AuthenticationService(
        enabled=True,
        verifier=StaticVerifier({"sub": "user-1", "roles": ["reader"]}),
    )
    application = _application(authentication)
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        allowed = await client.get("/rag", headers={"Authorization": "Bearer valid"})
        forbidden = await client.get("/admin", headers={"Authorization": "Bearer valid"})

    assert allowed.status_code == 200
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "insufficient_scope"


@pytest.mark.anyio
async def test_missing_and_invalid_tokens_return_bearer_challenge() -> None:
    authentication = AuthenticationService(
        enabled=True,
        verifier=StaticVerifier(invalid=True),
    )
    application = _application(authentication)
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/rag")
        invalid = await client.get("/rag", headers={"Authorization": "Bearer invalid"})

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert invalid.json()["code"] == "authentication_required"


@pytest.mark.anyio
async def test_rate_limit_uses_subject_and_returns_retry_after() -> None:
    limiter = ControllableLimiter(rate_decision=RateDecision(False, 17))
    authentication = AuthenticationService(
        enabled=True,
        verifier=StaticVerifier({"sub": "user-2", "scope": "rag:query"}),
    )
    application = _application(authentication, limiter)
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/rag", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 429
    assert response.headers["retry-after"] == "17"
    assert response.json()["code"] == "rate_limit_exceeded"
    assert limiter.rate_calls == [("search-minute", "subject-key:user-2")]


@pytest.mark.anyio
async def test_global_concurrency_lease_is_released_after_response() -> None:
    limiter = ControllableLimiter()
    authentication = AuthenticationService(
        enabled=True,
        verifier=StaticVerifier({"sub": "admin-1", "roles": ["admin"]}),
    )
    application = _application(authentication, limiter)
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/capacity", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 200
    assert len(limiter.acquired) == 1
    assert limiter.acquired[0][0:2] == ("answer-global", "all")
    assert limiter.released == limiter.acquired


@pytest.mark.anyio
async def test_global_concurrency_rejection_is_safe_service_saturation() -> None:
    limiter = ControllableLimiter(concurrency_decision=RateDecision(False, 9))
    authentication = AuthenticationService(
        enabled=True,
        verifier=StaticVerifier({"sub": "reader-1", "roles": ["reader"]}),
    )
    application = _application(authentication, limiter)
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/capacity", headers={"Authorization": "Bearer valid"})

    assert response.status_code == 503
    assert response.headers["retry-after"] == "9"
    assert response.json()["code"] == "concurrency_limit_exceeded"
    assert limiter.released == []
