# AES Database

The database component runs PostgreSQL 16 with pgvector. The first implemented
slice provides durable users and opaque server-side sessions for the AES
Workbench. It also stores recoverable execution runs, progress, and final responses.
The same service will later hold synchronized conversations,
LangGraph checkpoints, artifact metadata, and retrieval embeddings.

See [architecture.md](architecture.md) for the complete ownership and schema
design.

## Required Configuration

From the repository root, create the ignored deployment environment file:

```bash
cp deploy/.env.example deploy/.env
```

Replace both password placeholders with different random values before running
Compose. The application role password is passed separately to LangGraph; it
is not embedded in a database URL, so URL-special characters are supported.
Docker Compose loads `deploy/.env` automatically because the top-level
Compose entrypoints are located in `deploy/`.

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

## Connection Recovery

LangGraph reuses a process-local PostgreSQL pool for login/session checks and
run persistence. The defaults need no additional configuration:

| Variable | Default | Meaning |
| --- | --- | --- |
| `AES_DB_CONNECT_TIMEOUT` | `5` | Seconds allowed to establish a new connection |
| `AES_DB_POOL_MIN_SIZE` | `2` | Warm connections per API process |
| `AES_DB_POOL_MAX_SIZE` | `8` | Maximum connections per API process |
| `AES_DB_POOL_TIMEOUT` | `10` | Seconds to wait for an available checked connection |

Override these in `deploy/.env` when needed. Pooling follows Psycopg's connection
checking and background reconnection behavior. During a brief outage, run
heartbeats retry and log recovery; graph-node progress waits in a local buffer.
Final response persistence retries without repeating the numerical solve.
Runs can still be marked interrupted after 120 seconds without a renewed lease.

To inspect database-side errors and current connection counts from the server:

```bash
docker logs --since 20m aes-postgres
docker exec aes-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT application_name, state, count(*) FROM pg_stat_activity GROUP BY application_name, state;"'
```

## Current Slice Boundary

The implemented database boundary authenticates users and protects chat,
invoke, run, and artifact HTTP endpoints. Migration `002_workflow_runs.sql`
persists execution requests, node progress, final responses, and worker heartbeats.
Each run has user ownership checks and can be retrieved after a browser refresh.
It does not yet persist full conversations or
associate existing artifact directories with a user. Per-user authorization of
chat threads and artifacts is part of the next persistence slice; do not
treat this first authentication gate as complete multi-tenant isolation.
