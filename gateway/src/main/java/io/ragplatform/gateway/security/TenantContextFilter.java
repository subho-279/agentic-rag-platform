package io.ragplatform.gateway.security;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.List;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.filter.OncePerRequestFilter;

/** Turns the validated JWT's claims into a {@link TenantContext}; rejects tokens without a valid tenant. */
public class TenantContextFilter extends OncePerRequestFilter {

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth instanceof JwtAuthenticationToken token) {
            TenantContext ctx = fromJwt(token.getToken());
            if (ctx == null) {
                response.setStatus(HttpServletResponse.SC_FORBIDDEN);
                response.setContentType("application/json");
                response.getWriter().write("{\"error\":\"token has no valid tenant_id claim\"}");
                return;
            }
            request.setAttribute(TenantContext.REQUEST_ATTRIBUTE, ctx);
        }
        chain.doFilter(request, response);
    }

    static TenantContext fromJwt(Jwt jwt) {
        String tenant = jwt.getClaimAsString("tenant_id");
        if (!TenantContext.isValidTenant(tenant)) {
            return null;
        }
        List<String> roles = jwt.getClaimAsStringList("roles");
        return new TenantContext(tenant, jwt.getSubject(), TenantContext.sanitizeRoles(roles));
    }
}
