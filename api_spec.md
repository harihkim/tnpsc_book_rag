# TNPSC Book RAG API v1

Status: **frontend contract frozen for the MVP; implementation is phased**

This document is the normative product-level contract for API v1. The checked-in
`openapi.v1.yaml` is the machine-readable contract for implemented and planned routes, and is the
source for frontend types and mocks. FastAPI's generated OpenAPI document will be tested against
the matching implemented operations as endpoints are delivered.

The words **must**, **must not**, **should**, and **may** describe contract requirements. A route
marked `planned` is part of the frozen contract but is not yet available in the running backend.

## 1. Implementation status

| Area | Method and path | Status |
|---|---|---|
| Liveness | `GET /health/live` | Implemented |
| Readiness | `GET /health/ready` | Implemented |
| Capabilities | `GET /v1/capabilities` | Planned |
| Catalog filters | `GET /v1/catalog/filters` | Planned |
| Books | `GET /v1/books` | Planned |
| Books | `POST /v1/books` | Planned |
| Book detail | `GET /v1/books/{book_id}` | Planned |
| Document upload | `POST /v1/books/{book_id}/documents` | Planned |
| Document detail | `GET /v1/documents/{document_id}` | Planned |
| Ingestion operations | `GET /v1/ingestion-runs` | Planned |
| Ingestion history | `GET /v1/documents/{document_id}/ingestion-runs` | Planned |
| Ingestion detail | `GET /v1/ingestion-runs/{run_id}` | Planned |
| Ingestion retry | `POST /v1/ingestion-runs/{run_id}/retry` | Planned |
| Page inspection | `GET /v1/documents/{document_id}/pages` | Planned |
| Page inspection | `GET /v1/pages/{page_id}` | Planned |
| Printed page correction | `PATCH /v1/pages/{page_id}` | Planned |
| Chunk inspection | `GET /v1/documents/{document_id}/chunks` | Planned |
| Citation source | `GET /v1/sources/{chunk_id}` | Planned |
| Asset metadata | `GET /v1/assets/{asset_id}` | Planned |
| Asset content | `GET /v1/assets/{asset_id}/content` | Planned |
| Asset thumbnail | `GET /v1/assets/{asset_id}/thumbnail` | Planned |
| Semantic search | `POST /v1/search` | Planned |
| Answer generation | `POST /v1/answers` | Planned |
| Answer recovery | `GET /v1/answers/{answer_id}` | Planned |

Unimplemented routes are absent; the backend does not expose placeholder responses. The frontend
should use mocks until a route is marked implemented.

## 2. Scope and trust boundaries

API v1 supports:

- English Tamil Nadu State Board textbooks for standards 6 through 10.
- Digital PDFs with a usable text layer. Scanned-only PDFs are rejected; OCR is not performed.
- Preservation and controlled serving of extracted images and figures.
- Standalone semantic search with textbook provenance.
- Textbook-grounded answers and explicitly separated general supplementation.
- Polling for ingestion progress.

API v1 does not support authentication, user accounts, deletion, OCR, Tamil content, WebSockets, or
direct access to storage keys. Answer generation supports optional server-sent event streaming;
other resources remain request/response or polling based. Catalog mutation and
extraction-inspection routes are administrative even though local MVP development has no auth.
Authentication and authorization are required before those routes are exposed publicly.

## 3. General conventions

### 3.1 URLs and media types

- Versioned resources use the `/v1` prefix. Health probes remain unversioned.
- Canonical paths do not end in `/`.
- JSON requests use `Content-Type: application/json`.
- JSON responses use `Content-Type: application/json`.
- Errors use `Content-Type: application/problem+json`.
- Streaming answer responses use `Content-Type: text/event-stream`.
- PDF upload uses `multipart/form-data`.
- Asset content uses the stored, validated asset media type.
- All text is UTF-8.

The deployment origin is configuration. Frontends must not hardcode a development host or port.
FastAPI publishes the schema for currently implemented routes at `GET /openapi.json`; CI compares
that implemented subset with `openapi.v1.yaml`.

### 3.2 Browser and CORS contract

The MVP supports direct browser calls as well as same-origin calls through SvelteKit. Configured
frontend origins receive CORS responses with credentials disabled and `Vary: Origin`.

- Allowed methods: `GET`, `POST`, `PATCH`, and `OPTIONS`.
- Allowed request headers: `Accept`, `Authorization`, `Content-Type`, `Idempotency-Key`,
  `If-None-Match`, and `X-Request-ID`.
- Exposed response headers: `Content-Disposition`, `ETag`, `Location`, `Retry-After`, and
  `X-Request-ID`.
- Preflight responses may be cached for 600 seconds.

Development origins are configured explicitly; production does not use a wildcard origin.
`Authorization` is preflight-compatible for a future authenticated deployment but has no effect in
the unauthenticated MVP.

### 3.3 Field representation

- JSON field names use `snake_case`.
- Resource IDs are lowercase UUID strings.
- Timestamps are RFC 3339 UTC timestamps such as `2026-07-15T09:30:00Z`.
- `standard` is an integer and is one of `6`, `7`, `8`, `9`, or `10`.
- `language` is the string `english` in v1.
- Nullable fields are present with `null` when no value is known.
- Collection fields are present as empty arrays rather than `null`.
- Stored PDF page indexes are zero-based. A frontend fallback label should display
  `PDF page {pdf_page_index + 1}` when `printed_page_label` is `null`.
- Generated explanation text blocks contain plain text, not HTML or Markdown. Line breaks may be
  preserved. Frontends must escape text-block content before rendering it.

### 3.4 Request validation and response evolution

Request bodies are closed objects: unknown fields receive a `422 validation_error`. Strings are
trimmed before validation unless they represent uploaded filenames or binary content. An empty
string is not a substitute for `null`.

Validation `errors.field` values use a stable location grammar: `body.filters.standards.0`,
`query.limit`, `path.book_id`, `header.Idempotency-Key`, `form.file`, or `form.edition`. Array
indexes are zero-based. The frontend may map these locations directly to form controls.

Clients should ignore unknown response fields. The server may add optional response fields without
changing the API version, but it will not rename fields, change their meaning, or add enum values
to v1 without a compatibility review.

### 3.5 Request correlation

Clients may send `X-Request-ID` using a UUID or another safe, printable identifier. The server
always returns the accepted or generated `X-Request-ID` response header. Unsafe or oversized values
are replaced. The answer response also includes `request_id` because it is commonly copied into
feedback and diagnostics.

Request IDs are diagnostic identifiers, not authentication credentials or idempotency keys.

### 3.6 Idempotent mutations

These operations require an `Idempotency-Key` header:

- `POST /v1/books`
- `POST /v1/books/{book_id}/documents`
- `POST /v1/ingestion-runs/{run_id}/retry`

The key must contain 8 to 128 characters from `A-Z`, `a-z`, `0-9`, `.`, `_`, `:`, and `-`. A
client should use a UUID. The backend guarantees replay of the original status and response for at
least 24 hours. Reusing a key with a different request body, multipart metadata, or upload checksum
returns `409 idempotency_conflict`.

`PATCH /v1/pages/{page_id}` is naturally idempotent and does not use this header.

### 3.7 Pagination and ordering

List endpoints accept:

- `limit`: integer, default `20`, minimum `1`, maximum `100`.
- `cursor`: optional opaque string returned by the previous response.
- `include_count`: boolean, default `false`. When true, the server performs an exact count for the
  active filters.

The common response is:

```json
{
  "items": [],
  "previous_cursor": null,
  "next_cursor": null,
  "total_items": null
}
```

Clients must not parse or construct cursors. A cursor belongs to the exact filter set and endpoint
that produced it; using it with different filters returns `422 invalid_cursor`.

`previous_cursor` and `next_cursor` support adjacent navigation. They are `null` at the beginning
and end respectively. Arbitrary page-number jumps are not supported; administrative tables should
use Previous/Next controls or retain a client-side stack of visited cursors. On `invalid_cursor`, a
client should clear its cursor history and reload the first page while preserving filters.

`total_items` is an integer when `include_count=true` and is otherwise `null`. It is the exact
number of matching items when that page is queried, not a snapshot guarantee: concurrent catalog
or ingestion changes may alter the count on a later page. Clients should request it for
administrative totals, not for ordinary infinite scrolling.

Default order is stable:

- Books: `standard`, case-insensitive `subject`, case-insensitive `title`, then `id`.
- Ingestion runs: newest `created_at` first, then `id`.
- Pages: `pdf_page_index`, then `id`.
- Chunks: `sequence_number`, then `id`.
- Semantic results: descending similarity, with a stable backend tie-breaker.

## 4. Errors

All non-2xx JSON errors from versioned `/v1` routes use one Problem Details-compatible shape:

```json
{
  "type": "urn:tnpsc-book-rag:problem:validation-error",
  "title": "Validation failed",
  "status": 422,
  "detail": "One or more request fields are invalid.",
  "instance": "/v1/search",
  "code": "validation_error",
  "request_id": "019bd75c-b0c4-7d1e-9e36-6b2f438b2378",
  "errors": [
    {
      "field": "body.query",
      "code": "too_short",
      "message": "Query must contain at least one non-whitespace character."
    }
  ]
}
```

`errors` is always an array and is empty for errors that are not field-specific. `detail` and
validation messages are safe for display. Responses never disclose stack traces, filesystem paths,
storage keys, database details, prompts, provider credentials, or textbook content not otherwise
returned by the requested resource.

Stable error codes are:

| HTTP status | `code` | Meaning |
|---|---|---|
| 400 | `bad_request` | The request cannot be interpreted outside normal field validation. |
| 404 | `not_found` | The resource does not exist or is not visible to the caller. |
| 409 | `duplicate_source` | The same PDF checksum is already registered in the corpus. |
| 409 | `idempotency_conflict` | An idempotency key was reused for a different operation. |
| 409 | `invalid_state` | The requested lifecycle operation is not allowed in the current state. |
| 409 | `ingestion_active` | The document already has a queued or running ingestion. |
| 413 | `payload_too_large` | The configured upload limit was exceeded. |
| 415 | `unsupported_media_type` | The upload is not a PDF by declared type and detected signature. |
| 422 | `validation_error` | One or more request fields are invalid. |
| 422 | `invalid_cursor` | The pagination cursor is malformed, expired, or used with other filters. |
| 422 | `unsupported_document` | The PDF is encrypted, corrupt, scanned-only, or has no usable text layer. |
| 429 | `capacity_exceeded` | A bounded local or generation capacity limit was reached. |
| 503 | `database_unavailable` | PostgreSQL is unavailable. |
| 503 | `storage_unavailable` | Artifact storage is unavailable. |
| 503 | `retrieval_unavailable` | Query embedding or vector retrieval is temporarily unavailable. |
| 503 | `generation_unavailable` | All configured generation providers are unavailable. |
| 500 | `internal_error` | An unexpected server error occurred. |

Provider-specific error names and quotas are not part of the public contract. A `Retry-After`
header may accompany `429` or `503` responses.

For an SSE answer request, an error detected before streaming starts uses the normal HTTP status and
Problem Details body. Once stream headers have been sent, a terminal `answer.failed` event carries
the same safe Problem Details object and the stream closes.

Health probes are the only exception: `/health/ready` returns its readiness body with
`status: "not_ready"` and HTTP `503` so an orchestrator receives the same bounded dependency
checks on both readiness outcomes.

## 5. Resource schemas

This section defines reusable response shapes. Examples use realistic placeholder IDs.

### 5.1 Book

```json
{
  "id": "3c508224-5f38-4721-b22c-31f9a043e877",
  "title": "Science — Standard 8",
  "standard": 8,
  "subject": "Science",
  "language": "english",
  "publisher": "Tamil Nadu Textbook and Educational Services Corporation",
  "catalog_identifier": null,
  "catalog_status": "ready",
  "document_count": 2,
  "active_document_id": "2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
  "latest_document_id": "2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
  "latest_document_state": "ready",
  "created_at": "2026-07-15T09:30:00Z",
  "updated_at": "2026-07-15T09:30:00Z"
}
```

Constraints:

- `title`: 1 to 500 characters.
- `subject`: 1 to 200 characters.
- `publisher`: 1 to 300 characters.
- `catalog_identifier`: `null` or 1 to 200 characters.
- `catalog_status`: `empty`, `processing`, `ready`, or `failed`.
- `document_count`: non-negative number of registered editions.
- `active_document_id`: the searchable document ID or `null` when the book has no active ready
  document.
- `latest_document_id` and `latest_document_state`: both `null` when `document_count` is zero;
  otherwise they identify the newest registered edition and its current state.

`catalog_status` is `ready` whenever an active document exists, even if a newer replacement is
processing or failed. In that case `latest_document_state` lets the administration UI show both
facts. Without an active document, status is `processing` for a non-terminal latest document,
`failed` for a failed latest document, and `empty` when no document exists.

Book detail adds a `documents` array of document summaries. The array includes all registered
editions, with the active edition first and remaining documents newest first.

### 5.2 Document summary

```json
{
  "id": "2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
  "book_id": "3c508224-5f38-4721-b22c-31f9a043e877",
  "edition": "2025–2026",
  "source_filename": "science-standard-8.pdf",
  "media_type": "application/pdf",
  "source_sha256": "9ce128fe2f0d23d4a921f763717cc36a902c579db9e8ab6318e6b05a2ca3d865",
  "file_size_bytes": 18425031,
  "page_count": 212,
  "state": "ready",
  "activated_at": "2026-07-15T10:02:41Z",
  "created_at": "2026-07-15T09:31:04Z",
  "updated_at": "2026-07-15T10:02:41Z"
}
```

`state` is one of `uploaded`, `queued`, `extracting`, `chunking`, `embedding`, `ready`, or
`failed`. `page_count` and `activated_at` may be `null`. Artifact locations and Docling artifacts
are internal and are never returned.

Document detail adds `latest_ingestion_run`, which is an ingestion run or `null`.

### 5.3 Ingestion run

```json
{
  "id": "cb5d573f-8331-42bf-99a6-73a43092e109",
  "document_id": "2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
  "status": "running",
  "current_stage": "chunking",
  "retry_count": 0,
  "started_at": "2026-07-15T09:31:12Z",
  "completed_at": null,
  "warnings": [],
  "error": null,
  "created_at": "2026-07-15T09:31:04Z",
  "updated_at": "2026-07-15T09:43:19Z"
}
```

`status` is one of `queued`, `running`, `succeeded`, or `failed`. `current_stage` is one of
`queued`, `extraction`, `chunking`, `embedding`, or `activation`. The API does not fabricate a
percentage from these stages.

Valid status/stage semantics are:

| `status` | Meaning of `current_stage` | Timestamp and error rules |
|---|---|---|
| `queued` | Next stage the worker will execute. Initially `queued`; after retry, the stage that previously failed. | `started_at`, `completed_at`, and `error` are `null`. |
| `running` | Stage currently executing. | `started_at` is non-null; `completed_at` and `error` are `null`. |
| `failed` | Stage that failed. | `started_at`, `completed_at`, and `error` are non-null. |
| `succeeded` | Always `activation`. | `started_at` and `completed_at` are non-null; `error` is `null`. |

Retry preserves warnings, increments `retry_count`, retains the failed stage as the next stage, and
clears `started_at`, `completed_at`, and `error`. The frontend should render stage labels from this
matrix rather than infer a percentage.

Each warning or error uses a sanitized issue shape:

```json
{
  "code": "page_text_empty",
  "message": "No usable text was extracted from this page.",
  "stage": "extraction",
  "pdf_page_index": 17
}
```

`stage` and `pdf_page_index` may be `null`. Worker IDs, configuration fingerprints, library
versions, and embedding model details remain internal.

### 5.4 Page summary and detail

```json
{
  "id": "0406f9bc-7855-4f4b-89c5-9cb2f4ae2ba9",
  "document_id": "2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
  "pdf_page_index": 17,
  "printed_page_label": "12",
  "width": 612.0,
  "height": 792.0,
  "warning_count": 0,
  "created_at": "2026-07-15T09:35:48Z"
}
```

Width and height may be `null` and use the source PDF's page-coordinate units. Page detail adds:

```json
{
  "raw_text": "12  FORCE AND PRESSURE ...",
  "normalized_text": "FORCE AND PRESSURE ...",
  "warnings": [],
  "assets": [],
  "chunks": []
}
```

The complete detail response contains both the summary and detail fields in one object. Text may be
an empty string for a page containing only images. `assets` contains asset metadata and `chunks`
contains chunk summaries.

### 5.5 Chunk summary

```json
{
  "id": "fda7e283-d42f-4b17-8a17-34cce0f35a01",
  "page_id": "0406f9bc-7855-4f4b-89c5-9cb2f4ae2ba9",
  "document_id": "2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
  "sequence_number": 84,
  "display_text": "Pressure is the force acting perpendicularly on a unit area.",
  "chapter_title": "Force and Pressure",
  "section_path": ["Force and Pressure", "Pressure"],
  "content_type": "prose",
  "token_count": 15,
  "created_at": "2026-07-15T09:44:07Z"
}
```

`chapter_title` may be `null`. `content_type` is one of `prose`, `heading`, `list`, `table`,
`caption`, or `mixed`. Embedding text, embedding vectors, internal checksums, and raw provenance
payloads are not returned.

### 5.6 Asset metadata

```json
{
  "id": "d8fac5f1-0d7d-47f1-9dc1-cbde7a3069d7",
  "page_id": "0406f9bc-7855-4f4b-89c5-9cb2f4ae2ba9",
  "asset_type": "diagram",
  "mime_type": "image/png",
  "sha256": "2845c7a1a31d5d16b4471e08334df0f3d4c34a93e8dd75ad4f580b41d84fca40",
  "pixel_width": 1280,
  "pixel_height": 668,
  "caption": "Pressure exerted by a force on different areas",
  "alt_text": "Diagram comparing pressure produced by the same force over two contact areas.",
  "alt_text_source": "manual",
  "is_decorative": false,
  "bounding_box": {
    "x_min": 82.4,
    "y_min": 214.7,
    "x_max": 526.1,
    "y_max": 446.3,
    "coordinate_origin": "top_left"
  },
  "content_url": "/v1/assets/d8fac5f1-0d7d-47f1-9dc1-cbde7a3069d7/content",
  "thumbnail_url": "/v1/assets/d8fac5f1-0d7d-47f1-9dc1-cbde7a3069d7/thumbnail",
  "thumbnail_pixel_width": 640,
  "thumbnail_pixel_height": 334,
  "created_at": "2026-07-15T09:40:22Z"
}
```

`asset_type` is one of `image`, `diagram`, `map`, `photograph`, `figure`, or `unknown`.
`caption`, `alt_text`, and `bounding_box` may be `null`. `pixel_width` and `pixel_height` are
positive intrinsic pixel dimensions and are both present for raster assets; both may be `null` for
a vector asset with no intrinsic raster size. A bounding box uses page-coordinate units and a
`coordinate_origin` of `top_left` or `bottom_left`. Pixel dimensions are intentionally named
differently from a page's PDF-coordinate `width` and `height`.

Accessibility rules are closed and frontend-safe:

- `alt_text_source` is `caption`, `manual`, `unavailable`, or `not_applicable`.
- A decorative asset has `is_decorative=true`, `alt_text=null`, and
  `alt_text_source=not_applicable`; the frontend renders `alt=""`.
- A described informative asset has non-null `alt_text` and a source of `caption` or `manual`.
- An informative asset awaiting remediation has `alt_text=null` and
  `alt_text_source=unavailable`. It remains visible to administration, but student-facing views
  must not silently render it with empty alt text.

Raster assets have a canonical thumbnail with a longest edge of at most 640 pixels. The thumbnail
preserves aspect ratio and is produced during ingestion, not resized on demand. `thumbnail_url` and
both thumbnail dimensions are non-null for raster assets and all three are `null` for unsupported
vector assets. When the original already fits within the bound, the thumbnail endpoint may return
the original bytes and dimensions.

## 6. Capabilities and health endpoints

### `GET /v1/capabilities`

Returns public implementation features and client-relevant limits for the running deployment. It
contains no provider, path, or credential details and uses `Cache-Control: no-store`.

```json
{
  "api_version": "v1",
  "features": {
    "catalog_mutation": true,
    "ingestion_inspection": true,
    "semantic_search": true,
    "answer_generation": true,
    "answer_streaming": true,
    "answer_recovery": true
  },
  "limits": {
    "max_upload_bytes": 52428800,
    "max_query_characters": 1000,
    "max_top_k": 50,
    "max_answer_characters_per_section": 8000,
    "answer_timeout_seconds": 60,
    "answer_retention_seconds": 86400,
    "thumbnail_max_edge_pixels": 640
  },
  "upload": {
    "accepted_media_types": ["application/pdf"],
    "requires_text_layer": true
  }
}
```

Feature flags describe implemented runtime behavior, not user entitlements. A frontend must hide or
disable unavailable features rather than probe absent routes. Values may differ between a partial
development backend and a complete deployment; field names and meanings remain stable within v1.

### `GET /health/live`

Returns `200` when the API process can serve requests:

```json
{
  "status": "ok"
}
```

This does not assert that the database, storage, embedding model, worker, or LLM providers are
available.

### `GET /health/ready`

Returns `200` only when required API dependencies are ready. It returns `503` with the same body
shape when any required dependency is unavailable.

```json
{
  "status": "ok",
  "checks": {
    "database": "ok",
    "artifact_storage": "ok"
  }
}
```

Possible check values are `ok`, `unavailable`, and, where a dependency is optional in the active
configuration, `not_configured`. Health responses intentionally contain no connection details.

## 7. Catalog endpoints

### `GET /v1/catalog/filters`

Returns filter options derived only from active, ready English documents. It is intended for the
search UI, not catalog administration.

```json
{
  "standards": [6, 7, 8, 9, 10],
  "subjects": ["English", "Science", "Social Science"],
  "books": [
    {
      "id": "3c508224-5f38-4721-b22c-31f9a043e877",
      "title": "Science — Standard 8",
      "standard": 8,
      "subject": "Science"
    }
  ]
}
```

Arrays may be empty before any document becomes ready.

### `GET /v1/books`

Lists conceptual books, including books without a ready document. Optional query parameters:

- `standard`: repeatable; each value is 6 through 10.
- `subject`: repeatable exact subject value, matched case-insensitively.
- `q`: trimmed title/subject substring, 1 to 200 characters.
- `limit`, `cursor`, and `include_count`: common pagination parameters.

Returns the common paginated response with book items.

### `POST /v1/books`

Administrative. Requires `Idempotency-Key`.

```json
{
  "title": "Science — Standard 8",
  "standard": 8,
  "subject": "Science",
  "language": "english",
  "publisher": "Tamil Nadu Textbook and Educational Services Corporation",
  "catalog_identifier": null
}
```

`language` may be omitted and defaults to `english`; no other value is accepted. Returns `201`
with a Book resource and a `Location: /v1/books/{book_id}` header.

### `GET /v1/books/{book_id}`

Returns `200` with the Book fields plus `documents`. Returns `404 not_found` for an unknown book.

## 8. Document and ingestion endpoints

### `POST /v1/books/{book_id}/documents`

Administrative. Uploads and queues one digital PDF. Requires `Idempotency-Key` and
`multipart/form-data` with:

- `file`: required PDF binary.
- `edition`: required trimmed string, 1 to 200 characters.

The backend validates both the declared media type and PDF signature, streams the file through a
bounded upload path, computes its checksum, stores it immutably, creates the document and ingestion
run transactionally, and returns `202`:

```json
{
  "document": {
    "id": "2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
    "book_id": "3c508224-5f38-4721-b22c-31f9a043e877",
    "edition": "2025–2026",
    "source_filename": "science-standard-8.pdf",
    "media_type": "application/pdf",
    "source_sha256": "9ce128fe2f0d23d4a921f763717cc36a902c579db9e8ab6318e6b05a2ca3d865",
    "file_size_bytes": 18425031,
    "page_count": null,
    "state": "queued",
    "activated_at": null,
    "created_at": "2026-07-15T09:31:04Z",
    "updated_at": "2026-07-15T09:31:04Z"
  },
  "ingestion_run": {
    "id": "cb5d573f-8331-42bf-99a6-73a43092e109",
    "document_id": "2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
    "status": "queued",
    "current_stage": "queued",
    "retry_count": 0,
    "started_at": null,
    "completed_at": null,
    "warnings": [],
    "error": null,
    "created_at": "2026-07-15T09:31:04Z",
    "updated_at": "2026-07-15T09:31:04Z"
  },
  "poll_after_seconds": 2,
  "links": {
    "document": "/v1/documents/2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
    "ingestion_run": "/v1/ingestion-runs/cb5d573f-8331-42bf-99a6-73a43092e109"
  }
}
```

The upload response means the file and durable queue record were accepted; it does not mean
extraction succeeded. A checksum already registered anywhere in the corpus returns
`409 duplicate_source`. If encrypted or scan-only content is discovered after acceptance, the run
ends in `failed` with a sanitized `unsupported_document` ingestion issue.

### `GET /v1/documents/{document_id}`

Returns a document detail with `latest_ingestion_run`. A document is searchable only when `state`
is `ready` and `activated_at` is non-null.

### `GET /v1/ingestion-runs`

Administrative operations view. Accepts common pagination parameters and optional repeatable
`status`, repeatable `stage`, `book_id`, and `document_id` filters. Each paginated item contains:

```json
{
  "ingestion_run": {
    "id": "cb5d573f-8331-42bf-99a6-73a43092e109",
    "document_id": "2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
    "status": "running",
    "current_stage": "chunking",
    "retry_count": 0,
    "started_at": "2026-07-15T09:31:12Z",
    "completed_at": null,
    "warnings": [],
    "error": null,
    "created_at": "2026-07-15T09:31:04Z",
    "updated_at": "2026-07-15T09:43:19Z"
  },
  "document": {
    "id": "2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
    "edition": "2025–2026",
    "source_filename": "science-standard-8.pdf",
    "state": "chunking"
  },
  "book": {
    "id": "3c508224-5f38-4721-b22c-31f9a043e877",
    "title": "Science — Standard 8",
    "standard": 8,
    "subject": "Science"
  }
}
```

This is the global queue/history surface; the frontend does not fetch every book and document to
build an operations table. Default order is newest run first.

### `GET /v1/documents/{document_id}/ingestion-runs`

Accepts common pagination parameters and returns ingestion runs newest first.

### `GET /v1/ingestion-runs/{run_id}`

Returns the ingestion run. Responses include `Cache-Control: no-store`. Frontends should poll at
the latest `poll_after_seconds` hint, defaulting to two seconds, stop on `succeeded` or `failed`,
and back off after network errors. The response is:

```json
{
  "ingestion_run": {
    "id": "cb5d573f-8331-42bf-99a6-73a43092e109",
    "document_id": "2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
    "status": "running",
    "current_stage": "embedding",
    "retry_count": 0,
    "started_at": "2026-07-15T09:31:12Z",
    "completed_at": null,
    "warnings": [],
    "error": null,
    "created_at": "2026-07-15T09:31:04Z",
    "updated_at": "2026-07-15T09:58:31Z"
  },
  "poll_after_seconds": 3
}
```

The server does not promise a completion time or expose a synthetic percentage.

### `POST /v1/ingestion-runs/{run_id}/retry`

Administrative. Requires `Idempotency-Key`. Requeues the same failed run and increments
`retry_count`; it does not create a second run. The associated document moves from `failed` to
`queued`. Only a failed run may be retried, and a document may have at most one queued or running
run. Returns `202` with the same response shape as ingestion detail.

A succeeded run and a ready document are immutable. To ingest a corrected or replacement edition,
upload a new document under the book. If that new edition fails, the previously active ready
document remains searchable.

## 9. Extraction inspection endpoints

These routes are administrative/development inspection surfaces.

### `GET /v1/documents/{document_id}/pages`

Accepts common pagination parameters and returns page summaries in PDF order. Partial pages may be
visible for a failed ingestion so extraction failures can be inspected.

### `GET /v1/pages/{page_id}`

Returns complete page detail, including text, warnings, asset metadata, and chunk summaries.

### `PATCH /v1/pages/{page_id}`

Corrects only the human-facing printed label:

```json
{
  "printed_page_label": "12"
}
```

The value is `null` or a trimmed string of at most 100 characters. `null` removes a correction.
Returns `200` with the complete page detail. It does not change `pdf_page_index`.

### `GET /v1/documents/{document_id}/chunks`

Accepts common pagination parameters plus optional `page_id`. A supplied page must belong to the
document. Returns chunk summaries in document sequence order.

### `GET /v1/sources/{chunk_id}`

Public read endpoint used by search results and answer citations. Returns the same evidence shape
embedded in search and answer responses, including `page_id`, book/document provenance, source
text, assets, and `source_url`. A source remains addressable when its document is no longer active
so saved answers retain valid citations.

The source view is the MVP citation destination. Original textbook PDFs are preserved internally
but are not publicly served in v1; this avoids turning a citation feature into an unrestricted PDF
download surface. The frontend may render the evidence as a route, drawer, or popover using the
stable `source_url`.

### `GET /v1/assets/{asset_id}`

Returns asset metadata.

### `GET /v1/assets/{asset_id}/content`

Streams the preserved asset. The response includes:

- The validated stored `Content-Type`.
- `X-Content-Type-Options: nosniff`.
- `ETag` derived from the content checksum.
- `Cache-Control: private, max-age=86400`.
- `Content-Disposition: inline` for approved raster image types; otherwise `attachment`.

The endpoint supports `If-None-Match` and may return `304`. Byte-range requests are not part of
the MVP. The frontend should use `content_url` rather than constructing storage paths.

### `GET /v1/assets/{asset_id}/thumbnail`

Returns the canonical bounded raster thumbnail described by asset metadata. It uses the same
`ETag`, `If-None-Match`, `X-Content-Type-Options`, and private caching behavior as original content,
and always uses `Content-Disposition: inline`. It returns `404 not_found` when the asset has no
thumbnail representation. List and search views should prefer `thumbnail_url`; detailed source
views may load `content_url` on demand.

## 10. Semantic search

### `POST /v1/search`

Search is local and does not require an LLM provider.

Request:

```json
{
  "query": "Why does a sharp knife cut more easily?",
  "top_k": 10,
  "filters": {
    "standards": [8],
    "subjects": ["Science"],
    "book_ids": [],
    "document_ids": []
  }
}
```

Constraints and defaults:

- `query`: trimmed, 1 to 1000 characters.
- `top_k`: integer, default `10`, minimum `1`, maximum `50`.
- `filters`: optional object; each omitted array defaults to `[]`.
- Filter values must be unique. `standards` accepts at most 5 values, `subjects` at most 20, and
  each UUID filter at most 50.
- Multiple values within one filter are ORed. Different filter fields are ANDed.
- Subject matching is case-insensitive against canonical catalog subjects.
- Only active, ready English documents participate, even when a document ID is supplied.

With the default `Accept: application/json` representation, the response is:

```json
{
  "query": "Why does a sharp knife cut more easily?",
  "top_k": 10,
  "filters": {
    "standards": [8],
    "subjects": ["Science"],
    "book_ids": [],
    "document_ids": []
  },
  "results": [
    {
      "rank": 1,
      "score": 0.8462,
      "score_kind": "cosine_similarity",
      "evidence": {
        "chunk_id": "fda7e283-d42f-4b17-8a17-34cce0f35a01",
        "page_id": "0406f9bc-7855-4f4b-89c5-9cb2f4ae2ba9",
        "document_id": "2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
        "book_id": "3c508224-5f38-4721-b22c-31f9a043e877",
        "book_title": "Science — Standard 8",
        "edition": "2025–2026",
        "standard": 8,
        "subject": "Science",
        "pdf_page_index": 17,
        "printed_page_label": "12",
        "section_path": ["Force and Pressure", "Pressure"],
        "content_type": "prose",
        "text": "A sharp knife has a smaller contact area and therefore produces more pressure for the same force.",
        "assets": [
          {
            "id": "d8fac5f1-0d7d-47f1-9dc1-cbde7a3069d7",
            "asset_type": "diagram",
            "caption": "Pressure exerted by a force on different areas",
            "alt_text": "Diagram comparing pressure produced by the same force over two contact areas.",
            "alt_text_source": "manual",
            "is_decorative": false,
            "pixel_width": 1280,
            "pixel_height": 668,
            "content_url": "/v1/assets/d8fac5f1-0d7d-47f1-9dc1-cbde7a3069d7/content",
            "thumbnail_url": "/v1/assets/d8fac5f1-0d7d-47f1-9dc1-cbde7a3069d7/thumbnail",
            "thumbnail_pixel_width": 640,
            "thumbnail_pixel_height": 334
          }
        ],
        "source_url": "/v1/sources/fda7e283-d42f-4b17-8a17-34cce0f35a01"
      }
    }
  ]
}
```

`results` may be empty and ranks are contiguous from 1. A score is a model-specific ranking signal,
not a probability or calibrated confidence value; frontends must not present it as a confidence
percentage. The backend does not promise a stable numeric threshold across embedding revisions.

Search returns extracted evidence only. It never returns generated prose.

Asset references embedded in search results and answer citations use the same accessibility,
intrinsic-size, content, and thumbnail fields shown above. This lets the frontend choose an
accessible representation and reserve an aspect-ratio box before fetching bytes.

## 11. Answer generation

### `POST /v1/answers`

Answer generation performs retrieval, bounded context assembly, and optional LLM generation.

Request:

```json
{
  "query": "Why does a sharp knife cut more easily?",
  "mode": "textbook_only",
  "top_k": 10,
  "response_length": "medium",
  "filters": {
    "standards": [8],
    "subjects": ["Science"],
    "book_ids": [],
    "document_ids": []
  }
}
```

- `query`, `top_k`, and `filters` follow the search constraints.
- `mode` is required and is `textbook_only` or `textbook_plus_general`.
- `response_length` is optional, defaults to `medium`, and is `short`, `medium`, or `long`.
  It is a bounded style preference, not an exact word or token guarantee.

Response:

```json
{
  "answer_id": "895e220e-f9d2-4950-a2cb-07af92bf2b32",
  "query": "Why does a sharp knife cut more easily?",
  "mode": "textbook_only",
  "textbook": {
    "status": "answered",
    "blocks": [
      {
        "type": "paragraph",
        "nodes": [
          {
            "type": "text",
            "content": "A sharp knife concentrates the applied force over a smaller contact area. This creates greater pressure, so it cuts the material more easily. "
          },
          {
            "type": "citation",
            "citation_id": "T1",
            "fallback_text": "[T1]"
          }
        ]
      }
    ],
    "citations": [
      {
        "citation_id": "T1",
        "chunk_id": "fda7e283-d42f-4b17-8a17-34cce0f35a01",
        "page_id": "0406f9bc-7855-4f4b-89c5-9cb2f4ae2ba9",
        "document_id": "2e55606d-d0e1-4bbd-9052-1a39dd71a56a",
        "book_id": "3c508224-5f38-4721-b22c-31f9a043e877",
        "book_title": "Science — Standard 8",
        "edition": "2025–2026",
        "standard": 8,
        "subject": "Science",
        "pdf_page_index": 17,
        "printed_page_label": "12",
        "section_path": ["Force and Pressure", "Pressure"],
        "content_type": "prose",
        "text": "A sharp knife has a smaller contact area and therefore produces more pressure for the same force.",
        "assets": [],
        "source_url": "/v1/sources/fda7e283-d42f-4b17-8a17-34cce0f35a01"
      }
    ]
  },
  "supplementary": null,
  "request_id": "019bd75c-b0c4-7d1e-9e36-6b2f438b2378",
  "created_at": "2026-07-15T10:20:18Z"
}
```

The `textbook` object has:

- `status`: `answered` or `insufficient_evidence`.
- `blocks`: a non-empty ordered array of semantic `paragraph` and `bullet_list` blocks. The sum of
  text content is at most 8,000 characters. For insufficient evidence, it contains a short
  paragraph abstention and no citation nodes.
- `citations`: exact evidence records labeled `T1`, `T2`, and so on. It is empty when evidence is
  insufficient.

A paragraph is `{"type": "paragraph", "nodes": [...]}`. A bullet list is
`{"type": "bullet_list", "items": [[...], [...]]}` where each item is an inline-node array.
Inline nodes are text (`{"type": "text", "content": "..."}`) or citations
(`{"type": "citation", "citation_id": "T1", "fallback_text": "[T1]"}`). Every citation node
must resolve to exactly one returned citation, and every returned citation must be used by at least
one node. `fallback_text` is backend-generated from `citation_id`; it is not accepted from the
model. The frontend renders paragraphs and semantic lists without parsing newlines or
LLM-authored citation syntax.

For `textbook_only`, `supplementary` is always `null`. Material factual claims in the textbook
explanation must be supported by citations or the response must abstain.

For `textbook_plus_general`, `supplementary` is either `null` or:

```json
{
  "kind": "general_knowledge",
  "blocks": [
    {
      "type": "paragraph",
      "nodes": [
        {
          "type": "text",
          "content": "In material science, edge geometry and friction can also affect cutting performance."
        }
      ]
    }
  ]
}
```

Supplementary text is visually and structurally separate. Its `kind` is always
`general_knowledge`, allowing the frontend to own localized display copy. Its blocks may contain
only text nodes, must not imply that general claims occur on a cited page, and have the same 8,000
character bound. It may be present even when `textbook.status` is `insufficient_evidence`.
Choosing this mode permits supplementation; it does not guarantee that supplementation will be
necessary.

The response does not expose provider or model names. They are retained in the internal answer-run
audit record. If generation providers are unavailable, this endpoint returns
`503 generation_unavailable`; `/v1/search` remains independent and available.

### Streaming representation

The same request supports streaming when the client explicitly sends:

```http
Accept: text/event-stream
```

The request body and final answer schema do not change. Because this is a `POST` with a JSON body,
browser clients use streaming `fetch`, not the native `EventSource` constructor. A missing `Accept`
header, `*/*`, or `application/json` selects the synchronous JSON representation.

The stream responds with `Content-Type: text/event-stream` and
`Cache-Control: no-cache, no-transform`. Each named event contains one JSON value in its `data`
field and a monotonically increasing integer `id`. Deployments must disable intermediary response
buffering for this route. The backend sends an SSE comment as a keepalive when no event has been
emitted for 15 seconds.

Event payload schemas are defined under `components.schemas` and the answer operation's
`x-sse-events` extension in `openapi.v1.yaml`. Clients must ignore unknown non-terminal event names
for forward compatibility and must treat an unknown payload shape for a known event as a protocol
error.

The event sequence is:

1. `answer.started` — always first, after request validation.
2. Zero or more `answer.progress` events for `retrieval`, `augmentation`, `generation`, or
   `validation`.
3. Zero or more provisional `answer.delta` events while generation is in progress.
4. Zero or more `answer.reset` events if a provider fallback or validation retry invalidates the
   provisional preview.
5. Exactly one terminal `answer.completed` or `answer.failed` event, followed by stream closure.

Example events:

```text
event: answer.started
id: 1
data: {"answer_id":"895e220e-f9d2-4950-a2cb-07af92bf2b32","request_id":"019bd75c-b0c4-7d1e-9e36-6b2f438b2378"}

event: answer.progress
id: 2
data: {"answer_id":"895e220e-f9d2-4950-a2cb-07af92bf2b32","stage":"generation"}

event: answer.delta
id: 3
data: {"answer_id":"895e220e-f9d2-4950-a2cb-07af92bf2b32","section":"textbook","content":"A sharp knife concentrates the applied force","provisional":true}
```

`answer.delta.section` is `textbook` or `supplementary`. Deltas append to a temporary plain-text
preview; they are not citation blocks and have not passed final grounding validation. The backend
may debounce or buffer provider output, so event boundaries are not token boundaries and cadence is
not guaranteed.

An `answer.reset` event has this shape and instructs the client to clear all provisional preview
text:

```text
event: answer.reset
id: 4
data: {"answer_id":"895e220e-f9d2-4950-a2cb-07af92bf2b32","reason":"generation_restarted"}
```

`answer.completed` carries the complete, validated JSON answer shown earlier as its `data` value.
The client must replace provisional text with the textbook and supplementary blocks in that
answer; this terminal event is the only canonical answer. `answer.failed` carries the Problem
Details object. Neither event exposes provider names or raw provider errors.

Automatic event replay is not part of v1. A POST stream cannot use `EventSource`'s automatic GET
reconnection semantics safely. Clients should use an `AbortController` for intentional
cancellation and must not automatically replay an interrupted generation request. Once
`answer.started` supplies an ID, the client recovers through the answer-result endpoint below.

### `GET /v1/answers/{answer_id}`

Returns durable answer-run state for at least the `answer_retention_seconds` advertised by
capabilities. It is the recovery path after an SSE connection loss:

```json
{
  "answer_id": "895e220e-f9d2-4950-a2cb-07af92bf2b32",
  "status": "succeeded",
  "request_id": "019bd75c-b0c4-7d1e-9e36-6b2f438b2378",
  "answer": {
    "answer_id": "895e220e-f9d2-4950-a2cb-07af92bf2b32",
    "query": "Why does a sharp knife cut more easily?",
    "mode": "textbook_only",
    "textbook": {
      "status": "insufficient_evidence",
      "blocks": [
        {
          "type": "paragraph",
          "nodes": [
            {
              "type": "text",
              "content": "The available textbook evidence is insufficient to answer this question."
            }
          ]
        }
      ],
      "citations": []
    },
    "supplementary": null,
    "request_id": "019bd75c-b0c4-7d1e-9e36-6b2f438b2378",
    "created_at": "2026-07-15T10:20:18Z"
  },
  "error": null,
  "created_at": "2026-07-15T10:20:18Z",
  "completed_at": "2026-07-15T10:20:27Z",
  "poll_after_seconds": null
}
```

`status` is `running`, `succeeded`, `failed`, or `cancelled`. Only `succeeded` has a non-null
`answer`; only `failed` has a non-null Problem Details `error`; `running` has a positive
`poll_after_seconds`; terminal states have it set to `null`. An intentional abort is best-effort:
the run may become `cancelled`, or may finish if the provider cannot be interrupted. After a network
loss, the frontend polls this endpoint instead of submitting a duplicate answer request.

## 12. Frontend implementation notes

- Keep the API origin in environment configuration.
- Load capabilities during application bootstrap and use feature flags and limits to configure
  routes, file inputs, validation, and timeouts.
- Use the exact v1 field and enum names; do not derive types from database concepts.
- Centralize JSON and SSE parsing, Problem Details parsing, `X-Request-ID`, timeouts, cancellation,
  and future bearer-auth support in one API client.
- Generate a new idempotency key for each user-initiated create, upload, or retry action and reuse
  it only when retrying the same request after an uncertain network result.
- A browser that displays byte-level PDF upload progress may use `XMLHttpRequest`; ordinary requests
  and answer streaming use `fetch`. Both use the same upload endpoint and idempotency behavior.
- Poll ingestion detail using `poll_after_seconds`, stop at `succeeded` or `failed`, and do not infer
  progress percentages from stages.
- Prefer `printed_page_label`; otherwise display one-based `pdf_page_index + 1` and label it as a
  PDF page.
- Request `include_count=true` only for views that display an exact administrative total.
- Treat search scores as optional expert/debug information, not user-facing confidence.
- Escape all extracted and generated text. Render answer nodes by their discriminated `type`; do not
  search generated strings for citation syntax.
- During SSE generation, render `answer.delta` only as a provisional preview, clear it on
  `answer.reset`, and replace it completely with the structured blocks from `answer.completed`.
- Do not announce every token through an ARIA live region; announce progress-stage changes and the
  final structured answer so streaming remains usable with a screen reader.
- After an SSE network loss, poll `GET /v1/answers/{answer_id}`. Do not submit the question again
  automatically.
- Render `supplementary.kind=general_knowledge` under localized general-knowledge copy and never
  merge it into textbook content.
- Citation interactions use `source_url`; they do not construct a page route from indexes.
- Fetch asset bytes only from `content_url`; never expect a filesystem or object-storage key.
- Prefer `thumbnail_url` in lists and lazy-load `content_url` in detailed source views.
- Reserve asset layout with `pixel_width / pixel_height` when available; fall back to the bounding
  box aspect ratio or a neutral placeholder when intrinsic dimensions are `null`.
- Use `alt_text` for informative assets, `alt=""` only when `is_decorative=true`, and keep assets
  with `alt_text_source=unavailable` out of student-facing inline content until remediated.
- Ignore additive unknown response fields, but handle unknown enum values as an unsupported backend
  version rather than silently assigning the wrong meaning.

For mock data, use valid UUIDs, RFC 3339 timestamps, zero-based PDF indexes, and all nullable and
array fields shown here. This reduces drift when mocks are replaced by the generated OpenAPI client.

## 13. Backend conformance and compatibility

As each planned route is implemented, the backend must add:

- Closed Pydantic request models and explicit response models.
- OpenAPI examples consistent with this document.
- In-process HTTP contract tests for success, validation, lifecycle conflicts, and safe errors.
- Streaming contract tests for event order, provisional reset, terminal completion/failure,
  disconnect cancellation, keepalives, and replacement by the canonical structured answer.
- Contract tests for CORS preflight/exposed headers, capabilities, source navigation, answer
  recovery/retention, accessible asset states, thumbnail dimensions, and ingestion state pairs.
- Tests that response schemas do not expose storage keys, embedding text/vectors, worker details,
  provider details, or unguarded exceptions.
- Database integration tests for filters, activation visibility, cursor stability, and transactional
  mutations.
- An update to the implementation-status table in this document.

Breaking changes require a new API version. Removing a field, renaming a field, changing nullability,
changing a field's meaning, tightening an accepted request without a migration period, or changing
an existing enum's meaning is breaking. Adding an optional response field is non-breaking.

`openapi.v1.yaml` is the machine-readable frontend source before and after route implementation.
This document remains the product-level contract and handoff; CI must detect disagreement between
the checked-in contract, generated implemented schema, endpoint examples, and contract tests.
