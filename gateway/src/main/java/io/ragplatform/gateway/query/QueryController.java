package io.ragplatform.gateway.query;

import io.ragplatform.gateway.audit.AuditRepository;
import io.ragplatform.gateway.security.TenantContext;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.io.IOException;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

@RestController
@RequestMapping("/api/v1/query")
public class QueryController {

    public record QueryRequest(@NotBlank @Size(max = 2000) String query) {}

    private final AgentClient agent;
    private final AuditRepository audit;

    public QueryController(AgentClient agent, AuditRepository audit) {
        this.agent = agent;
        this.audit = audit;
    }

    @PostMapping(produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> query(
            @RequestAttribute(TenantContext.REQUEST_ATTRIBUTE) TenantContext ctx,
            @RequestBody @jakarta.validation.Valid QueryRequest req)
            throws IOException, InterruptedException {
        audit(ctx, req.query());
        AgentClient.AgentResponse r = agent.query(ctx, req.query());
        return ResponseEntity.status(r.status()).contentType(MediaType.APPLICATION_JSON).body(r.body());
    }

    @PostMapping(value = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public StreamingResponseBody stream(
            @RequestAttribute(TenantContext.REQUEST_ATTRIBUTE) TenantContext ctx,
            @RequestBody @jakarta.validation.Valid QueryRequest req) {
        audit(ctx, req.query());
        return out -> {
            try {
                agent.stream(ctx, req.query(), out);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        };
    }

    private void audit(TenantContext ctx, String query) {
        audit.record(ctx, "query", "{\"sha256\":\"" + AuditRepository.sha256(query) + "\",\"length\":" + query.length() + "}");
    }
}
