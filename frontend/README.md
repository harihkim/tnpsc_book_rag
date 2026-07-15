# TNPSC Book RAG frontend

This directory is reserved for the SvelteKit and shadcn-svelte application.

Frontend work can proceed independently against the frozen product contract in
[`api_spec.md`](../api_spec.md). Generate request/response types and mock handlers from
[`openapi.v1.yaml`](../openapi.v1.yaml); do not infer public shapes from backend database models.

Only operations marked `x-implementation-status: implemented` are currently available from the
backend. Planned operations should remain behind mocks and the runtime feature flags returned by
`GET /v1/capabilities` once that endpoint is implemented.
