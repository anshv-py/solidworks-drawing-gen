# PostgreSQL

Used by the API in docker-compose / deployment (`CADAI_DATABASE_URL=postgresql+psycopg://...`).
Milestone 1 creates tables at startup (`Base.metadata.create_all`); Alembic migrations
are required before the first production deployment (see docs/ROADMAP.md).
