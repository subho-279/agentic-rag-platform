package io.ragplatform.gateway.security;

import java.util.List;
import java.util.regex.Pattern;

/** Identity derived from a validated JWT. Never built from request headers or bodies. */
public record TenantContext(String tenantId, String userId, List<String> roles) {

    public static final String REQUEST_ATTRIBUTE = "ragTenantContext";
    /** Reserved marker the ingestion worker uses to bypass role filtering inside its own tenant. */
    public static final String SYSTEM_ROLE = "__system__";

    private static final Pattern TENANT = Pattern.compile("^[A-Za-z0-9_-]{1,64}$");
    private static final Pattern ROLE = Pattern.compile("^[A-Za-z0-9_.:-]{1,64}$");

    public static boolean isValidTenant(String tenantId) {
        return tenantId != null && TENANT.matcher(tenantId).matches();
    }

    /** Keep only well-formed roles and drop the reserved system marker. */
    public static List<String> sanitizeRoles(List<String> raw) {
        if (raw == null) {
            return List.of();
        }
        return raw.stream()
                .filter(r -> r != null && ROLE.matcher(r).matches() && !SYSTEM_ROLE.equals(r))
                .distinct()
                .toList();
    }

    public String rolesCsv() {
        return String.join(",", roles);
    }
}
