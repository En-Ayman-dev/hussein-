# Deployment Guide

## Recommended Architecture

### Frontend: Vercel
- The frontend is a native `Next.js` app.
- Vercel provides first-class Next.js deployment, preview deployments, and CDN delivery.
- In a monorepo, Vercel supports importing the repository and selecting `frontend/` as the project root.

### Backend: Render
- The backend is a long-running `FastAPI` service with file uploads, cache, health checks, and database connections.
- Render fits this model better than serverless-only hosting because it runs a persistent Python web service.

### Database: Render Postgres
- The project requires `PostgreSQL` with `pgvector`.
- Render Postgres supports `pgvector` via `CREATE EXTENSION vector;`.
- Keeping the backend and database in the same provider and region reduces latency and simplifies operations.

### Cache / Rate Limiting: Render Key Value
- The application already supports Redis-compatible caching and rate limiting.
- Render Key Value is Redis-compatible and is suitable for this layer.

## Why This Split

- `Vercel` is the best fit for the `Next.js` frontend.
- `Render` is the better fit for the Python API and managed Postgres + cache.
- This keeps the provider count low while still matching each layer to the right runtime.

## Chosen Region

- `frankfurt`

This is the best current Render region choice for this project because it is closer to the expected user geography than the default US regions, while remaining officially supported.

## Deploy Backend on Render

The repository includes [render.yaml](./render.yaml), which provisions:

- `hussein-backend`
- `hussein-db`
- `hussein-cache`

### Steps

1. In Render, create a new Blueprint deployment from this repository.
2. Review the generated resources from `render.yaml`.
3. Provide:
   - `OPENAI_API_KEY` if you want `AI` mode and embeddings
   - `CORS_ALLOWED_ORIGINS` after you know your Vercel production URL
4. Deploy.

### Important Post-Deploy Check

After the database is ready, verify that `pgvector` is enabled. The app attempts to run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

If you want to confirm manually, connect to the Render Postgres instance and run:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## Deploy Frontend on Vercel

### Steps

1. Import the GitHub repository into Vercel.
2. When Vercel asks for the root directory, select `frontend`.
3. Set:

```env
NEXT_PUBLIC_API_BASE_URL=https://<your-render-backend>.onrender.com
```

4. Deploy.

### After Frontend Deployment

Copy the Vercel production domain and set it in Render:

```env
CORS_ALLOWED_ORIGINS=https://<your-vercel-domain>
```

If you keep Vercel preview deployments enabled, the backend is already prepared for them with:

```env
CORS_ALLOWED_ORIGIN_REGEX=^https://.*\.vercel\.app$
```

## Minimum Verification Checklist

### Backend
- `GET /api/health` returns healthy or degraded with database up
- `GET /api/stats` responds
- `GET /api/debug/database-audit` responds

### Frontend
- The chat page loads
- `AI` mode works when `OPENAI_API_KEY` is configured
- `without_ai` works without sending requests to OpenAI

### Database
- Uploading `TTL` works
- Reindex works when `OPENAI_API_KEY` is configured
- `concepts`, `concept_synonyms`, and `concept_relations` are populated
