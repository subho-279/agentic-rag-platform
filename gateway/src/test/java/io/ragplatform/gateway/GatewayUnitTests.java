package io.ragplatform.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import io.ragplatform.gateway.config.AppProperties;
import io.ragplatform.gateway.ingestion.DocumentRepository;
import io.ragplatform.gateway.ingestion.DocumentService;
import io.ragplatform.gateway.ratelimit.RateLimitFilter;
import io.ragplatform.gateway.ratelimit.TokenBucketRateLimiter;
import io.ragplatform.gateway.security.TenantContext;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.web.server.ResponseStatusException;

class GatewayUnitTests {

    @Test
    void tenantIdValidation() {
        assertThat(TenantContext.isValidTenant("acme-1_x")).isTrue();
        assertThat(TenantContext.isValidTenant("a b")).isFalse();
        assertThat(TenantContext.isValidTenant("x'; --")).isFalse();
        assertThat(TenantContext.isValidTenant("")).isFalse();
        assertThat(TenantContext.isValidTenant(null)).isFalse();
    }

    @Test
    void systemRoleAndMalformedRolesAreStripped() {
        List<String> roles = TenantContext.sanitizeRoles(List.of("hr", TenantContext.SYSTEM_ROLE, "bad role", "a,b", "}"));
        assertThat(roles).containsExactly("hr");
    }

    @Test
    void pgArrayLiteralFromSanitizedRoles() throws Exception {
        var m = DocumentRepository.class.getDeclaredMethod("toPgArray", List.class);
        m.setAccessible(true);
        assertThat(m.invoke(null, List.of("hr", "finance"))).isEqualTo("{hr,finance}");
        assertThat(m.invoke(null, List.of())).isEqualTo("{}");
    }

    @Test
    void filenameSanitisationBlocksTraversal() throws Exception {
        var m = DocumentService.class.getDeclaredMethod("sanitizeFilename", String.class);
        m.setAccessible(true);
        assertThat(m.invoke(null, "../../etc/passwd.txt")).isEqualTo("passwd.txt");
        assertThat(m.invoke(null, "C:\\temp\\report final.pdf")).isEqualTo("report_final.pdf");
        assertThatThrownBy(() -> {
            try {
                m.invoke(null, ".hidden");
            } catch (java.lang.reflect.InvocationTargetException e) {
                throw e.getCause();
            }
        }).isInstanceOf(ResponseStatusException.class);
    }

    @Test
    void rateLimitFilterChargesTenantBucketAndReturns429() throws Exception {
        var rl = new AppProperties.RateLimit(20, 5, 5, 5, true, Map.of());
        var denying = new TokenBucketRateLimiter(null, new AppProperties("s", false, "t", "u", "/tmp", "topic", rl)) {
            @Override
            public Decision tryAcquire(String tenantId, int cost) {
                return new Decision(false, 0, 1500);
            }
        };
        var filter = new RateLimitFilter(denying, rl);

        var req = new MockHttpServletRequest("POST", "/api/v1/query");
        req.setAttribute(TenantContext.REQUEST_ATTRIBUTE, new TenantContext("acme", "u1", List.of()));
        var res = new MockHttpServletResponse();
        var chain = new MockFilterChain();
        filter.doFilter(req, res, chain);

        assertThat(res.getStatus()).isEqualTo(429);
        assertThat(res.getHeader("Retry-After")).isEqualTo("2");
        assertThat(chain.getRequest()).isNull(); // request never reached the controller
    }

    @Test
    void queriesCostMoreThanReads() {
        var rl = new AppProperties.RateLimit(20, 5, 5, 5, true, Map.of());
        var filter = new RateLimitFilter(null, rl);
        assertThat(filter.costOf(new MockHttpServletRequest("POST", "/api/v1/query/stream"))).isEqualTo(5);
        assertThat(filter.costOf(new MockHttpServletRequest("POST", "/api/v1/documents"))).isEqualTo(5);
        assertThat(filter.costOf(new MockHttpServletRequest("GET", "/api/v1/documents"))).isEqualTo(1);
    }

    @Test
    void perTenantOverridesApply() {
        var rl = new AppProperties.RateLimit(20, 5, 5, 5, true, Map.of("big", new AppProperties.Limit(200, 50)));
        assertThat(rl.forTenant("big").capacity()).isEqualTo(200);
        assertThat(rl.forTenant("small").capacity()).isEqualTo(20);
    }
}
