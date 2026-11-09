-- Atomic token bucket. One Redis hash per tenant: {tokens, ts}.
-- KEYS[1] bucket key
-- ARGV[1] capacity, ARGV[2] refill tokens/second, ARGV[3] cost of this request
-- Returns {allowed (1|0), remaining tokens (floored), millis until `cost` tokens are available}
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])

local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)

local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now
end

local elapsed = math.max(0, now - ts)
tokens = math.min(capacity, tokens + elapsed * rate / 1000)

local allowed = 0
local retry_ms = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  retry_ms = math.ceil((cost - tokens) / rate * 1000)
end

redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'ts', tostring(now))
-- Idle buckets expire after twice the time needed to refill from empty.
redis.call('PEXPIRE', KEYS[1], math.ceil(capacity / rate * 1000) * 2)

return {allowed, math.floor(tokens), retry_ms}
