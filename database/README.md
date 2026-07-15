# AES Database

The database component runs PostgreSQL 16 with pgvector. The first implemented
slice provides durable users and opaque server-side sessions for the AES
Workbench. The same service will later hold conversations, workflow metadata,
LangGraph checkpoints, artifact metadata, and retrieval embeddings.

See [architecture.md](architecture.md) for the complete ownership and schema
design.

## Required Configuration

From the repository root, create an ignored `.env` file:

```bash
cp database/.env.example .env
```

Replace both password placeholders with different random values before running
Compose. The application role password is passed separately to LangGraph; it
is not embedded in a database URL, so URL-special characters are supported.

## Migrations

`aes-database-migrate` waits for PostgreSQL, ensures runtime roles exist, and
applies each versioned SQL file once. Applied versions are tracked in
`public.aes_schema_migration`.

Inspect migration logs with:

```bash
docker compose -f deploy/compose.dev.yaml logs aes-database-migrate
```

## Create The First User

After the stack is running:

```bash
docker compose -f deploy/compose.dev.yaml exec langgraph \
  python -m aes_agent.create_user --username engineer --display-name "AES Engineer"
```

The command reads and confirms the password interactively. It never accepts a
password as a command-line argument.

## Current Slice Boundary

The implemented database boundary authenticates users and protects chat,
invoke, and artifact HTTP endpoints. It does not yet persist conversations or
associate existing artifact directories with a user. Per-user authorization of
chat threads, runs, and artifacts is part of the next persistence slice; do not
treat this first authentication gate as complete multi-tenant isolation.
