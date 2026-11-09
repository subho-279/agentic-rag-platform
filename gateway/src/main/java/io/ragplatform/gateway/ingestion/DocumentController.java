package io.ragplatform.gateway.ingestion;

import io.ragplatform.gateway.security.TenantContext;
import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/v1/documents")
public class DocumentController {

    private final DocumentService service;
    private final DocumentRepository repository;

    public DocumentController(DocumentService service, DocumentRepository repository) {
        this.service = service;
        this.repository = repository;
    }

    /** Accepts the file, queues it, and returns immediately; poll GET /{id} for status. */
    @PostMapping(consumes = "multipart/form-data")
    public ResponseEntity<Map<String, Object>> upload(
            @RequestAttribute(TenantContext.REQUEST_ATTRIBUTE) TenantContext ctx,
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "allowedRoles", required = false, defaultValue = "") List<String> allowedRoles)
            throws IOException {
        UUID id = service.upload(ctx, file, allowedRoles);
        return ResponseEntity.status(HttpStatus.ACCEPTED).body(Map.of("documentId", id, "status", "PENDING"));
    }

    @GetMapping("/{id}")
    public ResponseEntity<DocumentRepository.DocumentView> get(
            @RequestAttribute(TenantContext.REQUEST_ATTRIBUTE) TenantContext ctx, @PathVariable UUID id) {
        // 404 (not 403) for rows RLS hides: callers cannot tell "other tenant's" from "does not exist".
        return repository.find(ctx, id).map(ResponseEntity::ok).orElseGet(() -> ResponseEntity.notFound().build());
    }

    @GetMapping
    public List<DocumentRepository.DocumentView> list(@RequestAttribute(TenantContext.REQUEST_ATTRIBUTE) TenantContext ctx) {
        return repository.list(ctx);
    }
}
