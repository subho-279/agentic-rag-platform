package io.ragplatform.gateway.ingestion;

import io.ragplatform.gateway.db.TenantJdbc;
import io.ragplatform.gateway.security.TenantContext;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.stereotype.Repository;

@Repository
public class DocumentRepository {

    public record DocumentView(
            UUID id, String filename, String status, List<String> allowedRoles, int chunkCount, String error, OffsetDateTime createdAt) {}

    private final TenantJdbc db;

    public DocumentRepository(TenantJdbc db) {
        this.db = db;
    }

    public void insertPending(TenantContext ctx, UUID id, String filename, String contentType, String storagePath, List<String> allowedRoles) {
        db.inTenant(ctx, jdbc -> jdbc.update(
                "INSERT INTO documents (id, tenant_id, filename, content_type, storage_path, status, allowed_roles, created_by) "
                        + "VALUES (?, ?, ?, ?, ?, 'PENDING', ?::text[], ?)",
                id, ctx.tenantId(), filename, contentType, storagePath, toPgArray(allowedRoles), ctx.userId()));
    }

    public void markFailed(TenantContext ctx, UUID id, String error) {
        // The gateway's role set may not include the document's allowed roles; an UPDATE needs the row to
        // be visible, so this only succeeds for roles that can see it. The uploader's own roles normally do.
        db.inTenant(ctx, jdbc -> jdbc.update(
                "UPDATE documents SET status = 'FAILED', error = ?, updated_at = now() WHERE id = ?", error, id));
    }

    public Optional<DocumentView> find(TenantContext ctx, UUID id) {
        return db.inTenant(ctx, jdbc -> jdbc.query(
                "SELECT id, filename, status, allowed_roles, chunk_count, error, created_at FROM documents WHERE id = ?",
                (rs, n) -> map(rs), id).stream().findFirst());
    }

    public List<DocumentView> list(TenantContext ctx) {
        return db.inTenant(ctx, jdbc -> jdbc.query(
                "SELECT id, filename, status, allowed_roles, chunk_count, error, created_at "
                        + "FROM documents ORDER BY created_at DESC LIMIT 100",
                (rs, n) -> map(rs)));
    }

    private static DocumentView map(java.sql.ResultSet rs) throws java.sql.SQLException {
        String[] roles = (String[]) rs.getArray("allowed_roles").getArray();
        return new DocumentView(
                rs.getObject("id", UUID.class),
                rs.getString("filename"),
                rs.getString("status"),
                List.of(roles),
                rs.getInt("chunk_count"),
                rs.getString("error"),
                rs.getObject("created_at", OffsetDateTime.class));
    }

    /** Postgres array literal from validated role names (the roles pattern excludes quotes, commas and braces). */
    static String toPgArray(List<String> roles) {
        return "{" + String.join(",", roles) + "}";
    }
}
