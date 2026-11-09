package io.ragplatform.gateway.config;

import java.util.Map;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app")
public record AppProperties(
        String jwtSecret,
        boolean devTokensEnabled,
        String internalToken,
        String agentUrl,
        String storageRoot,
        String ingestTopic,
        RateLimit rateLimit) {

    public record RateLimit(
            int capacity,
            double refillPerSecond,
            int queryCost,
            int uploadCost,
            boolean failOpen,
            Map<String, Limit> tenants) {

        public Limit forTenant(String tenantId) {
            Limit override = tenants == null ? null : tenants.get(tenantId);
            return override != null ? override : new Limit(capacity, refillPerSecond);
        }
    }

    public record Limit(int capacity, double refillPerSecond) {}
}
