package io.ragplatform.gateway.dev;

import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import io.ragplatform.gateway.config.AppProperties;
import io.ragplatform.gateway.security.TenantContext;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.Date;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * DEMO ONLY: mints JWTs so the demo script can act as users of different tenants without an identity provider.
 * Anyone who can reach this endpoint can impersonate any tenant. It exists only when app.dev-tokens-enabled=true.
 */
@RestController
@RequestMapping("/dev")
@ConditionalOnProperty(name = "app.dev-tokens-enabled", havingValue = "true")
public class DevTokenController {

    private static final Logger log = LoggerFactory.getLogger(DevTokenController.class);
    private final byte[] secret;

    public DevTokenController(AppProperties props) {
        this.secret = props.jwtSecret().getBytes(StandardCharsets.UTF_8);
        log.warn("DEV TOKEN ENDPOINT ENABLED (/dev/token): anyone can mint tokens for any tenant. Never use in production.");
    }

    @GetMapping("/token")
    public Map<String, String> token(
            @RequestParam String tenant,
            @RequestParam(defaultValue = "demo-user") String user,
            @RequestParam(defaultValue = "employee") List<String> roles) throws JOSEException {
        if (!TenantContext.isValidTenant(tenant)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid tenant id");
        }
        Instant now = Instant.now();
        JWTClaimsSet claims = new JWTClaimsSet.Builder()
                .subject(user)
                .claim("tenant_id", tenant)
                .claim("roles", TenantContext.sanitizeRoles(roles))
                .issueTime(Date.from(now))
                .expirationTime(Date.from(now.plusSeconds(3600)))
                .build();
        SignedJWT jwt = new SignedJWT(new JWSHeader(JWSAlgorithm.HS256), claims);
        jwt.sign(new MACSigner(secret));
        return Map.of("token", jwt.serialize(), "tenant", tenant, "user", user);
    }
}
