package io.ragplatform.gateway.ratelimit;

import io.ragplatform.gateway.config.AppProperties;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

/** Per-tenant token bucket in Redis, so one tenant's burst cannot consume another tenant's capacity. */
@Component
public class TokenBucketRateLimiter {

    private static final Logger log = LoggerFactory.getLogger(TokenBucketRateLimiter.class);

    public record Decision(boolean allowed, long remaining, long retryAfterMillis) {}

    private final StringRedisTemplate redis;
    private final AppProperties.RateLimit config;
    private final DefaultRedisScript<List> script;

    public TokenBucketRateLimiter(StringRedisTemplate redis, AppProperties props) {
        this.redis = redis;
        this.config = props.rateLimit();
        this.script = new DefaultRedisScript<>();
        this.script.setLocation(new ClassPathResource("scripts/token_bucket.lua"));
        this.script.setResultType(List.class);
    }

    public Decision tryAcquire(String tenantId, int cost) {
        AppProperties.Limit limit = config.forTenant(tenantId);
        try {
            List<?> result = redis.execute(
                    script,
                    List.of("rl:tenant:" + tenantId),
                    String.valueOf(limit.capacity()),
                    String.valueOf(limit.refillPerSecond()),
                    String.valueOf(cost));
            if (result == null || result.size() < 3) {
                return failMode("empty response from Redis");
            }
            return new Decision(
                    ((Number) result.get(0)).longValue() == 1L,
                    ((Number) result.get(1)).longValue(),
                    ((Number) result.get(2)).longValue());
        } catch (RuntimeException e) {
            return failMode(e.getMessage());
        }
    }

    private Decision failMode(String reason) {
        log.error("rate limiter unavailable ({}); failOpen={}", reason, config.failOpen());
        return config.failOpen() ? new Decision(true, -1, 0) : new Decision(false, 0, 1000);
    }
}
