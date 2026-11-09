package io.ragplatform.gateway.ingestion;

import io.ragplatform.gateway.config.AppProperties;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import org.springframework.stereotype.Service;

/**
 * Stores uploads on a volume shared with the worker. Layout: {@code <root>/<tenant>/<documentId>/<filename>}.
 * The tenant prefix is what the worker enforces before reading. To use S3/MinIO, replace this class and
 * send the object key in the Kafka event instead of a filesystem path.
 */
@Service
public class StorageService {

    private final Path root;

    public StorageService(AppProperties props) {
        this.root = Path.of(props.storageRoot()).toAbsolutePath().normalize();
    }

    /** @return the path relative to the storage root, which is what goes into the Kafka event. */
    public String store(String tenantId, String documentId, String safeFilename, InputStream data) throws IOException {
        Path target = root.resolve(tenantId).resolve(documentId).resolve(safeFilename).normalize();
        if (!target.startsWith(root.resolve(tenantId))) {
            throw new IOException("refusing to write outside the tenant directory");
        }
        Files.createDirectories(target.getParent());
        Files.copy(data, target, StandardCopyOption.REPLACE_EXISTING);
        return root.relativize(target).toString();
    }
}
