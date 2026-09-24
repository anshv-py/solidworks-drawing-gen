# API conventions

- Base path `/api`; JSON; snake_case fields; UUID string ids.
- Long-running work returns `202 Accepted` + `{ "job_id": ... }`; clients poll `GET /api/jobs/{id}`.
- Errors: `application/problem+json` `{type, title, status, detail, code}`; stable `code` strings (e.g. `UNSUPPORTED_FILE_TYPE`, `FILE_TOO_LARGE`, `INVALID_CAD_CONTENT`, `NOT_FOUND`, `JOB_NOT_COMPLETE`).
- Downloads stream files with `Content-Disposition: attachment` and a server-generated safe filename.
- Pagination: `?limit=&cursor=` when lists appear.
- Versioning: additive changes only within `/api`; schema_version fields on IR documents.
- Authentication-ready: every router depends on `get_principal()` (anonymous dev principal today) so auth can be inserted without touching handlers.
