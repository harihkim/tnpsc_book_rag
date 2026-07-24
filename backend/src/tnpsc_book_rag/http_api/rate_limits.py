"""Shared Redis/Valkey rate and concurrency enforcement for HTTP routes."""

# ruff: noqa: S105

import hashlib
import hmac
import ipaddress
import math
from dataclasses import dataclass
from secrets import token_urlsafe
from typing import Annotated, Protocol

from fastapi import Depends, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError

from tnpsc_book_rag.config import Settings
from tnpsc_book_rag.http_api.auth import Principal, current_principal
from tnpsc_book_rag.http_api.errors import ApiProblem

_TOKEN_BUCKET_SCRIPT = """
local values = redis.call('HMGET', KEYS[1], 'tokens', 'updated')
local tokens = tonumber(values[1])
local updated = tonumber(values[2])
local now = tonumber(ARGV[1])
local refill_per_ms = tonumber(ARGV[2])
local capacity = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local ttl_ms = tonumber(ARGV[5])
if tokens == nil then
  tokens = capacity
  updated = now
else
  tokens = math.min(capacity, tokens + math.max(0, now - updated) * refill_per_ms)
end
local allowed = 0
local retry_ms = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  retry_ms = math.ceil((cost - tokens) / refill_per_ms)
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'updated', now)
redis.call('PEXPIRE', KEYS[1], ttl_ms)
return {allowed, retry_ms, math.floor(tokens)}
"""

_CONCURRENCY_ACQUIRE_SCRIPT = """
local now = tonumber(ARGV[1])
local expires = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if redis.call('ZCARD', KEYS[1]) >= limit then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local retry_ms = 1000
  if oldest[2] ~= nil then
    retry_ms = math.max(1000, tonumber(oldest[2]) - now)
  end
  return {0, retry_ms}
end
redis.call('ZADD', KEYS[1], expires, ARGV[4])
redis.call('PEXPIRE', KEYS[1], math.max(1000, expires - now))
return {1, 0}
"""


@dataclass(frozen=True, slots=True)
class RatePolicy:
    """One token-bucket quota."""

    name: str
    requests: int
    window_seconds: int
    burst: int


@dataclass(frozen=True, slots=True)
class ConcurrencyPolicy:
    """One leased concurrency quota."""

    name: str
    limit: int
    lease_seconds: int
    global_scope: bool = False
    rejection_status: int = 429


@dataclass(frozen=True, slots=True)
class RateDecision:
    """Result returned by an atomic rate-limit operation."""

    allowed: bool
    retry_after_seconds: int


class RateLimiter(Protocol):
    """Lifecycle and atomic operations required by route dependencies."""

    async def initialize(self) -> None: ...

    async def close(self) -> None: ...

    def subject_key(self, subject: str) -> str: ...

    def request_ip_key(self, request: Request) -> str: ...

    async def check_rate(self, policy: RatePolicy, identity: str) -> RateDecision: ...

    async def acquire_concurrency(
        self,
        policy: ConcurrencyPolicy,
        identity: str,
        token: str,
    ) -> RateDecision: ...

    async def release_concurrency(
        self,
        policy: ConcurrencyPolicy,
        identity: str,
        token: str,
    ) -> None: ...


class DisabledRateLimiter:
    """No-op limiter used only when validated non-production settings disable enforcement."""

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    def subject_key(self, subject: str) -> str:
        return subject

    def request_ip_key(self, request: Request) -> str:
        return _client_ip(request)

    async def check_rate(self, policy: RatePolicy, identity: str) -> RateDecision:
        return RateDecision(allowed=True, retry_after_seconds=0)

    async def acquire_concurrency(
        self,
        policy: ConcurrencyPolicy,
        identity: str,
        token: str,
    ) -> RateDecision:
        return RateDecision(allowed=True, retry_after_seconds=0)

    async def release_concurrency(
        self,
        policy: ConcurrencyPolicy,
        identity: str,
        token: str,
    ) -> None:
        return None


class RedisRateLimiter:
    """Atomic token buckets and expiring concurrency leases in shared Redis/Valkey."""

    def __init__(self, url: str, *, identity_hmac_secret: str) -> None:
        self._redis: Redis = Redis.from_url(
            url,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=5,
            health_check_interval=30,
        )
        self._identity_secret = identity_hmac_secret.encode()

    async def initialize(self) -> None:
        await self._redis.ping()

    async def close(self) -> None:
        await self._redis.aclose()

    def subject_key(self, subject: str) -> str:
        return self._identity_key(f"subject:{subject}")

    def request_ip_key(self, request: Request) -> str:
        return self._identity_key(f"ip:{_client_ip(request)}")

    def _identity_key(self, value: str) -> str:
        return hmac.new(self._identity_secret, value.encode(), hashlib.sha256).hexdigest()

    async def check_rate(self, policy: RatePolicy, identity: str) -> RateDecision:
        refill_per_ms = policy.requests / (policy.window_seconds * 1000)
        ttl_ms = max(policy.window_seconds * 2000, 1000)
        try:
            result = await self._redis.eval(
                _TOKEN_BUCKET_SCRIPT,
                1,
                f"tnpsc:rate:{policy.name}:{identity}",
                _unix_milliseconds(),
                refill_per_ms,
                policy.burst,
                1,
                ttl_ms,
            )
        except RedisError as error:
            raise RateLimitStoreUnavailable from error
        allowed, retry_ms, _ = _integer_result(result, expected=3)
        return RateDecision(bool(allowed), max(1, math.ceil(retry_ms / 1000)))

    async def acquire_concurrency(
        self,
        policy: ConcurrencyPolicy,
        identity: str,
        token: str,
    ) -> RateDecision:
        now = _unix_milliseconds()
        expires = now + policy.lease_seconds * 1000
        try:
            result = await self._redis.eval(
                _CONCURRENCY_ACQUIRE_SCRIPT,
                1,
                f"tnpsc:concurrency:{policy.name}:{identity}",
                now,
                expires,
                policy.limit,
                token,
            )
        except RedisError as error:
            raise RateLimitStoreUnavailable from error
        allowed, retry_ms = _integer_result(result, expected=2)
        return RateDecision(bool(allowed), max(1, math.ceil(retry_ms / 1000)))

    async def release_concurrency(
        self,
        policy: ConcurrencyPolicy,
        identity: str,
        token: str,
    ) -> None:
        try:
            await self._redis.zrem(f"tnpsc:concurrency:{policy.name}:{identity}", token)
        except RedisError:
            # The lease expires automatically; release failure must not replace the route response.
            return None


class RateLimitStoreUnavailable(RuntimeError):
    """Raised when the shared enforcement store cannot make a safe decision."""


PUBLIC_READ = RatePolicy("public-read-minute", 120, 60, 30)
SEARCH_MINUTE = RatePolicy("search-minute", 30, 60, 10)
SEARCH_DAILY = RatePolicy("search-daily", 300, 86_400, 30)
ANSWER_WINDOW = RatePolicy("answer-ten-minute", 5, 600, 2)
ANSWER_DAILY = RatePolicy("answer-daily", 30, 86_400, 5)
CATALOG_WRITE = RatePolicy("catalog-write-hour", 30, 3_600, 5)
UPLOAD_HOURLY = RatePolicy("upload-hour", 3, 3_600, 1)
UPLOAD_DAILY = RatePolicy("upload-daily", 10, 86_400, 2)
INSPECTION_READ = RatePolicy("inspection-read-minute", 120, 60, 30)
ADMIN_WRITE = RatePolicy("admin-write-hour", 30, 3_600, 5)

ANSWER_USER_CONCURRENCY = ConcurrencyPolicy("answer-user", 1, 90)
ANSWER_GLOBAL_CONCURRENCY = ConcurrencyPolicy(
    "answer-global",
    4,
    90,
    global_scope=True,
    rejection_status=503,
)
UPLOAD_USER_CONCURRENCY = ConcurrencyPolicy("upload-user", 1, 900)


def create_rate_limiter(settings: Settings) -> RateLimiter:
    """Create shared enforcement or the validated development no-op."""
    if not settings.rate_limiting_enabled:
        return DisabledRateLimiter()
    if settings.rate_limit_url is None:
        msg = "enabled rate limiting has no Redis-compatible URL"
        raise ValueError(msg)
    secret = (
        settings.rate_limit_ip_hmac_secret.get_secret_value()
        if settings.rate_limit_ip_hmac_secret is not None
        else "development-only-rate-limit-identity"
    )
    return RedisRateLimiter(
        str(settings.rate_limit_url.get_secret_value()),
        identity_hmac_secret=secret,
    )


def enforce_public_rate(policy: RatePolicy):
    """Rate-limit a public route by the router-observed client address."""

    async def enforce(request: Request) -> None:
        limiter: RateLimiter = request.app.state.rate_limiter
        await _check_rate(limiter, policy, limiter.request_ip_key(request))

    return enforce


def enforce_authenticated_rate(policy: RatePolicy):
    """Rate-limit a protected route by authenticated subject."""

    async def enforce(
        request: Request,
        principal: Annotated[Principal, Depends(current_principal)],
    ) -> None:
        limiter: RateLimiter = request.app.state.rate_limiter
        await _check_rate(limiter, policy, limiter.subject_key(principal.subject))

    return enforce


def enforce_concurrency(policy: ConcurrencyPolicy):
    """Lease a per-subject or global concurrency slot for the response lifetime."""

    async def enforce(
        request: Request,
        principal: Annotated[Principal, Depends(current_principal)],
    ):
        limiter: RateLimiter = request.app.state.rate_limiter
        identity = "all" if policy.global_scope else limiter.subject_key(principal.subject)
        token = token_urlsafe(24)
        try:
            decision = await limiter.acquire_concurrency(policy, identity, token)
        except RateLimitStoreUnavailable:
            raise _store_unavailable() from None
        if not decision.allowed:
            title = (
                "Service capacity exhausted"
                if policy.rejection_status == 503
                else "Concurrent request limit exceeded"
            )
            raise ApiProblem(
                status=policy.rejection_status,
                code="concurrency_limit_exceeded",
                title=title,
                detail="Wait for an active operation to finish before retrying.",
                headers=(("Retry-After", str(decision.retry_after_seconds)),),
            )
        try:
            yield
        finally:
            await limiter.release_concurrency(policy, identity, token)

    return enforce


async def _check_rate(limiter: RateLimiter, policy: RatePolicy, identity: str) -> None:
    try:
        decision = await limiter.check_rate(policy, identity)
    except RateLimitStoreUnavailable:
        raise _store_unavailable() from None
    if not decision.allowed:
        raise ApiProblem(
            status=429,
            code="rate_limit_exceeded",
            title="Rate limit exceeded",
            detail="Too many requests were made for this operation.",
            headers=(("Retry-After", str(decision.retry_after_seconds)),),
        )


def _store_unavailable() -> ApiProblem:
    return ApiProblem(
        status=503,
        code="rate_limit_store_unavailable",
        title="Request enforcement unavailable",
        detail="The service cannot safely admit this request right now.",
        headers=(("Retry-After", "5"),),
    )


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    candidate = forwarded_for.rsplit(",", 1)[-1].strip() if forwarded_for else ""
    if not candidate and request.client is not None:
        candidate = request.client.host
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        return "unknown"


def _integer_result(value: object, *, expected: int) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != expected:
        raise RateLimitStoreUnavailable
    try:
        converted: list[int] = []
        for item in value:
            if not isinstance(item, (int, str, bytes, bytearray)):
                raise TypeError
            converted.append(int(item))
        return tuple(converted)
    except (TypeError, ValueError) as error:
        raise RateLimitStoreUnavailable from error


def _unix_milliseconds() -> int:
    import time

    return time.time_ns() // 1_000_000


__all__ = [
    "ADMIN_WRITE",
    "ANSWER_DAILY",
    "ANSWER_GLOBAL_CONCURRENCY",
    "ANSWER_USER_CONCURRENCY",
    "ANSWER_WINDOW",
    "CATALOG_WRITE",
    "INSPECTION_READ",
    "PUBLIC_READ",
    "SEARCH_DAILY",
    "SEARCH_MINUTE",
    "UPLOAD_DAILY",
    "UPLOAD_HOURLY",
    "UPLOAD_USER_CONCURRENCY",
    "ConcurrencyPolicy",
    "DisabledRateLimiter",
    "RateDecision",
    "RateLimitStoreUnavailable",
    "RateLimiter",
    "RatePolicy",
    "RedisRateLimiter",
    "create_rate_limiter",
    "enforce_authenticated_rate",
    "enforce_concurrency",
    "enforce_public_rate",
]
