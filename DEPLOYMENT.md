# Deployment Guide

## Final No-Card Architecture

This is the recommended free deployment path without adding a payment card:

- `Vercel` for the frontend
- `Vercel` for the backend as a separate project rooted at `backend/`
- `Supabase` for PostgreSQL with `pgvector`
- No managed Redis in production for now

## Why This Architecture

### Frontend: Vercel
- The frontend is a native `Next.js` app.
- Vercel is the best operational fit for this layer.
- It supports monorepos cleanly by selecting `frontend/` as the project root.

### Backend: Vercel
- The backend is `FastAPI`.
- Vercel officially supports deploying FastAPI apps as Python functions.
- This keeps deployment simple and avoids adding another paid provider.
- The repository is already prepared for this with [backend/index.py](./backend/index.py) and [backend/vercel.json](./backend/vercel.json).

### Database: Supabase
- The project requires PostgreSQL plus `pgvector`.
- Supabase provides a free Postgres project tier and supports vector use cases.
- The application already works with any PostgreSQL connection string through `DATABASE_URL`.

## Important Operational Constraint

This stack is correct for free deployment, but one part must be handled carefully:

- chat and read endpoints are fine on Vercel
- heavy maintenance operations such as full ontology reindexing are better run locally against the Supabase database

Reason:
- Vercel Functions are a good fit for request/response APIs
- full embedding rebuilds can take much longer and are not the right production path for a free serverless function

## Production Shape

### Frontend Project on Vercel
- Root directory: `frontend`
- Framework: Next.js
- Required env:

```env
NEXT_PUBLIC_API_BASE_URL=https://<your-backend-project>.vercel.app
```

### Backend Project on Vercel
- Root directory: `backend`
- Entry point: `index.py`
- Required env:

```env
DATABASE_URL=postgresql://...
OPENAI_API_KEY=...
CORS_ALLOWED_ORIGINS=https://<your-frontend-project>.vercel.app
CORS_ALLOWED_ORIGIN_REGEX=^https://.*\.vercel\.app$
```

Optional:

```env
REDIS_URL=
```

If `REDIS_URL` is not set, the app falls back safely to local in-memory behavior.

### Database on Supabase
- Create a free Postgres project
- Use its connection string as `DATABASE_URL`
- Enable `pgvector`

If needed, the application also attempts:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

## Data Loading Strategy

Use Supabase as the persistent production database, but do the heavy bootstrap from your local machine:

1. Put the Supabase connection string in `backend/.env`
2. Run the backend locally
3. Upload `unified_ontology.ttl`
4. Run reindex locally if you want AI embeddings

This avoids serverless timeout pressure during the initial data preparation.

## Practical Deployment Order

1. Create a free Supabase project
2. Put the Supabase `DATABASE_URL` in the backend Vercel project
3. Deploy backend from `backend/`
4. Deploy frontend from `frontend/`
5. Set `NEXT_PUBLIC_API_BASE_URL` to the backend URL
6. Set backend `CORS_ALLOWED_ORIGINS` to the frontend URL
7. Run ontology upload and optional reindex from local machine against Supabase

## Minimum Verification Checklist

### Backend
- `GET /api/health` responds
- `GET /api/stats` responds
- `GET /api/debug/database-audit` responds

### Frontend
- The homepage loads
- chat requests reach the backend
- `without_ai` works

### Database
- `concepts`, `concept_synonyms`, and `concept_relations` are populated
- `documents` remains intentionally empty

## Official References

- Vercel FastAPI: https://vercel.com/docs/frameworks/backend/fastapi/
- Vercel limits: https://vercel.com/docs/limits/overview
- Vercel monorepos: https://vercel.com/docs/monorepos/monorepo-faq
- Supabase compute: https://supabase.com/docs/guides/platform/compute-and-disk
