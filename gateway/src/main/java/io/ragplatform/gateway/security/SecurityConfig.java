package io.ragplatform.gateway.security;

import io.ragplatform.gateway.config.AppProperties;
import io.ragplatform.gateway.ratelimit.RateLimitFilter;
import io.ragplatform.gateway.ratelimit.TokenBucketRateLimiter;
import java.nio.charset.StandardCharsets;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtDecoders;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.oauth2.server.resource.authentication.JwtGrantedAuthoritiesConverter;
import org.springframework.security.oauth2.server.resource.web.authentication.BearerTokenAuthenticationFilter;
import org.springframework.security.web.SecurityFilterChain;

/**
 * Stateless resource server. Tokens are HS256 JWTs so the project runs without an identity provider;
 * to use a real OIDC provider, replace {@link #jwtDecoder} with
 * {@code JwtDecoders.fromIssuerLocation(issuerUri)} and map your provider's tenant/role claims.
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    @Bean
    JwtDecoder jwtDecoder(AppProperties props, @Value("${app.oidc-issuer-uri:}") String issuerUri) {
        if (issuerUri != null && !issuerUri.isBlank()) {
            // Real identity provider: signature keys and issuer are discovered from the provider's metadata.
            // Tokens must carry a `tenant_id` claim and a `roles` array (configure a claim mapper in the IdP).
            return JwtDecoders.fromIssuerLocation(issuerUri.trim());
        }
        byte[] secret = props.jwtSecret() == null ? new byte[0] : props.jwtSecret().getBytes(StandardCharsets.UTF_8);
        if (secret.length < 32) {
            throw new IllegalStateException(
                    "Set OIDC_ISSUER_URI, or JWT_SECRET with at least 32 bytes (app.jwt-secret) for HS256 tokens");
        }
        return NimbusJwtDecoder.withSecretKey(new SecretKeySpec(secret, "HmacSHA256"))
                .macAlgorithm(MacAlgorithm.HS256)
                .build();
    }

    @Bean
    JwtAuthenticationConverter jwtAuthenticationConverter() {
        JwtGrantedAuthoritiesConverter authorities = new JwtGrantedAuthoritiesConverter();
        authorities.setAuthoritiesClaimName("roles");
        authorities.setAuthorityPrefix("ROLE_");
        JwtAuthenticationConverter converter = new JwtAuthenticationConverter();
        converter.setJwtGrantedAuthoritiesConverter(authorities);
        return converter;
    }

    @Bean
    SecurityFilterChain securityFilterChain(
            HttpSecurity http,
            AppProperties props,
            TokenBucketRateLimiter limiter,
            JwtAuthenticationConverter converter)
            throws Exception {
        // These filters are deliberately NOT beans: a Filter bean would also be auto-registered
        // in the servlet container and run twice.
        TenantContextFilter tenantFilter = new TenantContextFilter();
        RateLimitFilter rateLimitFilter = new RateLimitFilter(limiter, props.rateLimit());

        http.csrf(csrf -> csrf.disable())
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(a -> {
                    a.requestMatchers("/actuator/health/**").permitAll();
                    if (props.devTokensEnabled()) {
                        a.requestMatchers("/dev/**").permitAll();
                    }
                    a.requestMatchers(HttpMethod.POST, "/api/v1/documents").hasAnyRole("admin", "editor");
                    a.anyRequest().authenticated();
                })
                .oauth2ResourceServer(o -> o.jwt(j -> j.jwtAuthenticationConverter(converter)))
                .addFilterAfter(tenantFilter, BearerTokenAuthenticationFilter.class)
                .addFilterAfter(rateLimitFilter, TenantContextFilter.class)
                .httpBasic(b -> b.disable());
        return http.build();
    }
}
