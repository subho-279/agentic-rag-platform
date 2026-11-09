package io.ragplatform.gateway.ingestion;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.ragplatform.gateway.audit.AuditRepository;
import io.ragplatform.gateway.config.AppProperties;
import io.ragplatform.gateway.security.TenantContext;
import java.io.IOException;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

@Service
public class DocumentService {

    private static final Logger log = LoggerFactory.getLogger(DocumentService.class);
    static final Set<String> ALLOWED_EXTENSIONS = Set.of("pdf", "txt", "md", "csv");

    private final StorageService storage;
    private final DocumentRepository documents;
    private final AuditRepository audit;
    private final KafkaTemplate<String, String> kafka;
    private final ObjectMapper mapper;
    private final String topic;

    public DocumentService(
            StorageService storage,
            DocumentRepository documents,
            AuditRepository audit,
            KafkaTemplate<String, String> kafka,
            ObjectMapper mapper,
            AppProperties props) {
        this.storage = storage;
        this.documents = documents;
        this.audit = audit;
        this.kafka = kafka;
        this.mapper = mapper;
        this.topic = props.ingestTopic();
    }

    public UUID upload(TenantContext ctx, MultipartFile file, List<String> allowedRoles) throws IOException {
        String filename = sanitizeFilename(file.getOriginalFilename());
        String ext = filename.substring(filename.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
        if (file.isEmpty() || !ALLOWED_EXTENSIONS.contains(ext)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "file must be non-empty and one of " + ALLOWED_EXTENSIONS);
        }
        List<String> roles = TenantContext.sanitizeRoles(allowedRoles);

        UUID id = UUID.randomUUID();
        String path;
        try (var in = file.getInputStream()) {
            path = storage.store(ctx.tenantId(), id.toString(), filename, in);
        }
        documents.insertPending(ctx, id, filename, file.getContentType(), path, roles);

        // Key = tenant id: one tenant's documents stay ordered within a partition, tenants spread across partitions.
        try {
            String manifest = mapper.writeValueAsString(
                    Map.of("document_id", id.toString(), "tenant_id", ctx.tenantId(), "file_path", path));
            kafka.send(topic, ctx.tenantId(), manifest).get(10, TimeUnit.SECONDS);
        } catch (JsonProcessingException | ExecutionException | TimeoutException | InterruptedException e) {
            if (e instanceof InterruptedException) {
                Thread.currentThread().interrupt();
            }
            log.error("failed to publish ingest event for doc={} tenant={}", id, ctx.tenantId(), e);
            documents.markFailed(ctx, id, "could not queue document for processing");
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "ingestion queue unavailable");
        }
        audit.record(ctx, "document.upload", "{\"document_id\":\"" + id + "\"}");
        return id;
    }

    /** Keeps only the final path segment and a conservative character set. */
    static String sanitizeFilename(String original) {
        String name = original == null ? "" : original.replace('\\', '/');
        name = name.substring(name.lastIndexOf('/') + 1).replaceAll("[^A-Za-z0-9._-]", "_");
        if (name.isBlank() || name.startsWith(".") || !name.contains(".")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid file name");
        }
        return name.length() > 120 ? name.substring(name.length() - 120) : name;
    }
}
