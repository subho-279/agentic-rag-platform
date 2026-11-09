package io.ragplatform.gateway.ratelimit;

import io.ragplatform.gateway.config.AppProperties;
import io.ragplatform.gateway.security.TenantContext;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.web.filter.OncePerRequestFilter;

/** Charges the caller's tenant bucket. Runs after {@code TenantContextFilter}. Queries and uploads cost more than reads. */
public class RateLimitFilter extends OncePerRequestFilter {

    private final TokenBucketRateLimiter limiter;
    private final AppProperties.RateLimit config;

    public RateLimitFilter(TokenBucketRateLimiter limiter, AppProperties.RateLimit config) {
        this.limiter = limiter;
        this.config = config;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        Object attr = request.getAttribute(TenantContext.REQUEST_ATTRIBUTE);
        if (!(attr instanceof TenantContext ctx)) {
            chain.doFilter(request, response);
            return;
        }
        TokenBucketRateLimiter.Decision d = limiter.tryAcquire(ctx.tenantId(), costOf(request));
        if (d.remaining() >= 0) {
            response.setHeader("X-RateLimit-Remaining", String.valueOf(d.remaining()));
        }
        if (!d.allowed()) {
            long retrySeconds = Math.max(1, (d.retryAfterMillis() + 999) / 1000);
            response.setStatus(429);
            response.setHeader("Retry-After", String.valueOf(retrySeconds));
            response.setContentType("application/json");
            response.getWriter().write("{\"error\":\"tenant rate limit exceeded\",\"retryAfterSeconds\":" + retrySeconds + "}");
            return;
        }
        chain.doFilter(request, response);
    }

    public int costOf(HttpServletRequest request) {
        String path = request.getRequestURI();
        if (path.startsWith("/api/v1/query")) {
            return config.queryCost();
        }
        if ("POST".equals(request.getMethod()) && path.startsWith("/api/v1/documents")) {
            return config.uploadCost();
        }
        return 1;
    }
}
