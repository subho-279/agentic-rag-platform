package io.ragplatform.gateway.db;

import io.ragplatform.gateway.security.TenantContext;
import java.util.function.Function;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Runs JDBC work in a transaction whose Postgres session settings select the tenant and roles that
 * the Row-Level Security policies (db/init.sql) evaluate. Settings are transaction-local, so a pooled
 * connection never carries one tenant's identity into the next request.
 */
@Component
public class TenantJdbc {

    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;

    public TenantJdbc(JdbcTemplate jdbc, TransactionTemplate tx) {
        this.jdbc = jdbc;
        this.tx = tx;
    }

    public <T> T inTenant(TenantContext ctx, Function<JdbcTemplate, T> work) {
        return tx.execute(status -> {
            jdbc.queryForObject("SELECT set_config('app.current_tenant', ?, true)", String.class, ctx.tenantId());
            jdbc.queryForObject("SELECT set_config('app.current_roles', ?, true)", String.class, ctx.rolesCsv());
            return work.apply(jdbc);
        });
    }
}
