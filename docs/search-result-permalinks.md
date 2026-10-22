# Search result references and permalinks

## Current behavior

Search results contain the uploaded `file_id`, exact `chunk_id`, filename, chunk text, score, optional metadata, `permalink`, and `document_url`. `GET /v1/files/{file_id}` continues to return file metadata. S3 keys are private implementation details and are not exposed as links.

## Goals

- Let a caller identify the exact chunk returned by search.
- Let a caller retrieve that chunk and its source metadata later, while it remains indexed.
- Provide a separate way to open or download the original uploaded file.
- Keep references protected by the same LiteLLM key and ownership checks as the existing API.

## API

Each search result now includes these fields:

```json
{
  "file_id": "<uploaded-file-id>",
  "chunk_id": "<embedding-id>",
  "permalink": "/v1/vector_stores/<vector-store-id>/chunks/<chunk-id>",
  "document_url": "/v1/files/<uploaded-file-id>/content"
}
```

`file_id` is the uploaded file identifier. `chunk_id` is the exact `Embedding.id` for the matched passage. `permalink` resolves to the authenticated `GET /v1/vector_stores/{vector_store_id}/chunks/{chunk_id}` endpoint, which returns the chunk text, filename, title, and attributes. It identifies the indexed passage rather than recording a transient search score. `document_url` resolves to the authenticated `GET /v1/files/{file_id}/content` endpoint, which streams the original upload as an attachment with a safe `Content-Disposition` filename and `X-Content-Type-Options: nosniff`.

The permalink is a relative URL on the API origin. Clients can resolve it against the API URL they already use. Do not construct it from `VECTOR_STORE_API_BASE`: deployment documentation uses that setting for LiteLLM's internal service address, which may not be reachable by end users. If responses need absolute URLs, add a separate externally reachable `PUBLIC_API_BASE_URL` setting and use it only for link generation.

## Authorization and lifecycle

The chunk endpoint verifies that the caller owns the vector store and that the chunk belongs to that store. The document endpoint applies the existing file ownership scope before reading from S3. Both routes return 404 for unknown or unauthorized resources so IDs do not disclose other users' data. Links require normal API authentication; they are not bearer-free public sharing links.

Chunk IDs are valid while their embedding row exists. Detaching a file or deleting its vector store cascades to its chunks, so those permalinks then return 404. Deleting an attachment while retaining the uploaded file invalidates chunk links but leaves the document URL usable. Deleting the uploaded file invalidates both.

If links must survive re-ingestion or re-chunking, UUIDs for current embedding rows are not enough: those operations replace the rows. That stronger guarantee needs versioned source snapshots and stable chunk identities within each snapshot (for example, a source revision ID plus chunk ordinal and content hash). The initial endpoint should promise stability only for the lifetime of the indexed chunk.

## Follow-up

The current chunker stores text but does not retain page, heading, or character offsets. The first version links to the exact chunk text. To highlight the passage inside DOCX/PDF viewers later, preserve Docling provenance during chunking and add structured location metadata such as page number, heading path, and character range. This can be added to JSON metadata without a table migration.

If clients need absolute URLs, add an externally configured public API base. Do not build public links from the internal `VECTOR_STORE_API_BASE` setting.
