# Local Quickstart and API Contract

## Status

The current code is an early MVP: asset metadata registry and content-addressed artifact upload on local storage. It is not yet a production data lake, full governance engine, or migration-complete service.

## Run locally

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export TENSORDATA_API_KEY='replace-with-a-long-random-secret'
uvicorn tensordata.main:app --reload
```

Health: `GET http://localhost:8000/health`

Interactive API documentation: `http://localhost:8000/docs`

By default metadata uses `./data/tensordata.db` and artifact payloads use `./data/artifacts`. Configure `TENSORDATA_DATABASE_URL`, `TENSORDATA_STORAGE_ROOT`, and `TENSORDATA_MAX_UPLOAD_BYTES` for other environments. Keep the API key out of source control.

## Authentication

All `/api/v1` routes require `X-API-Key`. If `TENSORDATA_API_KEY` is not configured, data API access is disabled. The health endpoint is intentionally unauthenticated and returns no asset information.

This initial API-key mechanism is suitable only for controlled development and trusted internal deployment behind TLS/network controls. Production deployment still requires identity integration, scoped authorization, secret rotation, audit logging and rate limiting.

## Current endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Service health |
| POST | `/api/v1/assets` | Register an asset in quarantine |
| GET | `/api/v1/assets` | List/filter assets |
| GET | `/api/v1/assets/{asset_id}` | Read asset metadata |
| POST | `/api/v1/assets/{asset_id}/artifacts` | Upload immutable content-addressed artifact |
| GET | `/api/v1/assets/{asset_id}/artifacts` | List artifact metadata |

Example asset registration:

```bash
curl -X POST http://localhost:8000/api/v1/assets \
  -H 'X-API-Key: replace-with-a-long-random-secret' \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "ship motion observations",
    "asset_type": "timeseries",
    "owner": "tensor-physics",
    "rights_status": "review_required",
    "allowed_purposes": ["research"],
    "metadata": {"domain": "ship"}
  }'
```

Upload the source payload using the returned asset ID:

```bash
curl -X POST 'http://localhost:8000/api/v1/assets/ASSET_ID/artifacts' \
  -H 'X-API-Key: replace-with-a-long-random-secret' \
  -F 'file=@observations.csv'
```

The server computes SHA-256 and stores payloads under a digest-derived path. Duplicate payload bytes reuse the same content path. The original filename is metadata only and is never used to construct a storage path.

## Known limitations / next gates

- Database schema currently uses SQLAlchemy metadata creation; Alembic migrations are not yet implemented.
- The API key is a single shared secret, not user/service identity or resource-scoped authorization.
- Asset lifecycle transitions and approval gates are not yet exposed.
- Source registry, dataset manifests/versions, provenance, lineage and quality reports are not yet implemented.
- Local filesystem storage is for development; S3-compatible backend and retention/garbage collection are future work.
- The current upload handler enforces a configurable application-level size limit; production deployments also need proxy/server request limits and malware/content inspection.
- Run automated tests and add CI before treating this service as deployable.
