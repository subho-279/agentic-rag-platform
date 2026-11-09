package io.ragplatform.gateway.query;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.ragplatform.gateway.config.AppProperties;
import io.ragplatform.gateway.security.TenantContext;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;
import org.springframework.stereotype.Component;

/**
 * Calls the Python agent. The tenant and roles are taken from the validated JWT (a {@link TenantContext}),
 * never from the caller's request, and the shared internal token proves to the agent that the call came from here.
 */
@Component
public class AgentClient {

    // HTTP/1.1 is forced on purpose: by default the JDK client tries an HTTP/2 upgrade (Upgrade: h2c) on plain-HTTP
    // requests, and uvicorn answers those POSTs with 400/422 and drops the body. The agent speaks plain HTTP/1.1.
    private final HttpClient http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(3))
            .build();
    private final ObjectMapper mapper;
    private final String baseUrl;
    private final String internalToken;

    public AgentClient(ObjectMapper mapper, AppProperties props) {
        this.mapper = mapper;
        this.baseUrl = props.agentUrl().replaceAll("/+$", "");
        this.internalToken = props.internalToken();
    }

    public record AgentResponse(int status, String body) {}

    public AgentResponse query(TenantContext ctx, String query) throws IOException, InterruptedException {
        HttpResponse<String> r = http.send(request(ctx, "/internal/query", query), HttpResponse.BodyHandlers.ofString());
        return new AgentResponse(r.statusCode(), r.body());
    }

    /** Copies the agent's SSE stream to {@code out}, flushing as chunks arrive. Returns the upstream status. */
    public int stream(TenantContext ctx, String query, OutputStream out) throws IOException, InterruptedException {
        HttpResponse<InputStream> r = http.send(request(ctx, "/internal/query/stream", query), HttpResponse.BodyHandlers.ofInputStream());
        try (InputStream in = r.body()) {
            byte[] buf = new byte[1024];
            int n;
            while ((n = in.read(buf)) != -1) {
                out.write(buf, 0, n);
                out.flush();
            }
        }
        return r.statusCode();
    }

    private HttpRequest request(TenantContext ctx, String path, String query) throws JsonProcessingException {
        return HttpRequest.newBuilder(URI.create(baseUrl + path))
                .timeout(Duration.ofSeconds(120))
                .header("Content-Type", "application/json")
                .header("X-Internal-Token", internalToken)
                .header("X-Tenant-Id", ctx.tenantId())
                .header("X-User-Id", ctx.userId() == null ? "" : ctx.userId())
                .header("X-User-Roles", ctx.rolesCsv())
                .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(Map.of("query", query))))
                .build();
    }
}
