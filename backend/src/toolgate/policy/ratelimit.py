from __future__ import annotations

import time
from dataclasses import dataclass

from redis.asyncio import Redis

from toolgate.policy.schemas import RateLimit

# Token bucket evaluated atomically in Redis so limits hold across gateway replicas.
# Returns {allowed, tokens_left_x1000, retry_after_ms}.
_TOKEN_BUCKET = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1])
local ts = tonumber(state[2])
if tokens == nil then
  tokens = capacity
  ts = now
end

local elapsed = math.max(0, now - ts) / 1000.0
tokens = math.min(capacity, tokens + elapsed * rate)

local allowed = 0
local retry_after = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  retry_after = math.ceil(((cost - tokens) / rate) * 1000)
end

redis.call('HSET', key, 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('PEXPIRE', key, math.ceil((capacity / rate) * 1000) + 1000)
return {allowed, math.floor(tokens * 1000), retry_after}
"""


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    remaining: float
    retry_after_seconds: float


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_TOKEN_BUCKET)

    async def consume(self, key: str, limit: RateLimit, *, cost: int = 1, now_ms: int | None = None) -> RateLimitResult:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        raw = await self._script(keys=[key], args=[limit.capacity, limit.refill_per_second, now, cost])
        allowed, tokens_milli, retry_ms = (int(v) for v in raw)
        return RateLimitResult(
            allowed=allowed == 1, remaining=tokens_milli / 1000.0, retry_after_seconds=retry_ms / 1000.0
        )
