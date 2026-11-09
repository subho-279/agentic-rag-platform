package io.ragplatform.gateway.audit;

import io.ragplatform.gateway.db.TenantJdbc;
import io.ragplatform.gateway.security.TenantContext;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Repository;

@Repository
public class AuditRepository {

    private static final Logger log = LoggerFactory.getLogger(AuditRepository.class);
    private final TenantJdbc db;

    public AuditRepository(TenantJdbc db) {
        this.db = db;
    }

    /** Best-effort: an audit write failure is logged but never blocks the request. */
    public void record(TenantContext ctx, String action, String detailJson) {
        try {
            db.inTenant(ctx, jdbc -> jdbc.update(
                    "INSERT INTO audit_log (tenant_id, user_id, action, detail) VALUES (?, ?, ?, ?::jsonb)",
                    ctx.tenantId(), ctx.userId() == null ? "unknown" : ctx.userId(), action, detailJson));
        } catch (RuntimeException e) {
            log.warn("audit write failed for tenant={} action={}: {}", ctx.tenantId(), action, e.getMessage());
        }
    }

    /** Queries are logged as a hash plus length, not verbatim, to keep sensitive text out of the audit table. */
    public static String sha256(String text) {
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
