# AES Database Architecture

The `database/` component owns AES PostgreSQL deployment, schema migrations,
and durable application data. The first implemented slice provides pgvector,
server-side users, and opaque login sessions. Conversations, workflow records,
LangGraph checkpoints, artifact metadata, and retrieval indexes remain the
target described by this document.

## Decision

The first implementation should use one PostgreSQL container with the
`pgvector` extension.

- PostgreSQL provides users, sessions, conversations, messages, AES runs,
  workflow events, tool/model calls, LangGraph checkpoints, and artifact
  metadata.
- `pgvector` makes the same PostgreSQL service the first AES vector database
  for document chunks and embeddings.
- Large files remain in the AES artifact store. PostgreSQL stores their
  metadata, ownership, status, checksum, and URI, not the file bytes.
- A dedicated vector engine such as Qdrant or Weaviate is deferred until
  retrieval scale or operational requirements justify another service.

This is one physical database service, but it is not one unstructured schema.
Separate PostgreSQL schemas and roles preserve ownership boundaries.

## System Placement

```mermaid
flowchart LR
    subgraph CLIENTS["Client"]
        direction TB
        browser["Browser"] --> web["web-ui"]
    end

    subgraph ORCHESTRATION["Orchestration"]
        direction TB
        api["LangGraph API"] --> orchestrator["StateGraph"]
    end

    subgraph COMPUTE["Models and Tools"]
        direction TB
        ollama["Ollama"]
        fenics["FEniCS MCP"]
        retrieval["Retrieval MCP"]
    end

    subgraph PERSISTENCE["Persistence"]
        direction TB
        postgres[("PostgreSQL + pgvector")]
        artifacts[("Artifact Store<br/>files")]
    end

    web --> api
    orchestrator --> ollama
    orchestrator --> fenics
    orchestrator --> retrieval
    api --> postgres
    orchestrator --> postgres
    retrieval --> postgres
    orchestrator --> artifacts
```

The browser does not connect to PostgreSQL. The Workbench uses authenticated
HTTP APIs, and server-side services enforce authorization and ownership.

## Storage Boundaries

```mermaid
flowchart LR
    UI["web-ui"] --> API["LangGraph / AES API"]
    API --> ID[("identity schema")]
    API --> CHAT[("chat schema")]
    API --> WF[("workflow schema")]
    API --> CP[("checkpoint schema")]

    API --> FILES["AES artifact filesystem"]
    API --> META[("artifact schema")]

    API --> RET["Retrieval MCP"]
    RET --> VEC[("retrieval schema<br/>pgvector")]

    FILES -. "URI + checksum + ownership" .-> META
```

| PostgreSQL schema | Owner | Purpose |
| --- | --- | --- |
| `identity` | AES API | Users, password hashes, login sessions, authorization data |
| `chat` | AES API | Conversation threads and user/assistant messages |
| `workflow` | LangGraph/AES | Runs, node/route events, model calls, tool calls, final status |
| `checkpoint` | LangGraph checkpointer | Durable graph snapshots and pending writes for resume/recovery |
| `artifact` | Artifact-store integration | Metadata for files stored outside PostgreSQL |
| `retrieval` | Retrieval MCP | Collections, documents, chunks, embeddings, queries, and hits |

The target uses separate database roles:

- the configured PostgreSQL administrator currently applies bootstrap
  migrations and is not used by runtime services,
- `aes_app`: read/write access to `identity`, `chat`, `workflow`, and
  `artifact`,
- `aes_checkpoint`: access only to LangGraph checkpoint tables,
- `aes_retrieval`: access only to `retrieval`, including vector indexes,
- `aes_readonly`: optional diagnostics/reporting access.

The first migration creates `aes_app`, `aes_checkpoint`, and `aes_retrieval`.
Only `aes_app` is used by application code in the identity slice. A dedicated
non-administrator migration role and the optional read-only role are later
hardening steps.

## Current Persistence Inventory

The database introduction replaces or complements these current stores.

| Current data | Current location | Target |
| --- | --- | --- |
| User identity and login sessions | `identity.app_user` and `identity.auth_session` | Implemented; keep server-side |
| Conversations and turns | Browser `localStorage` | `chat.chat_thread` and `chat.chat_message` |
| Active conversation selection | Browser `localStorage` | Remains a UI preference; may be cached locally |
| `AgentState` | Process memory during `graph.invoke` | PostgreSQL LangGraph checkpointer |
| Run status and next action | Returned only in `aes_result` and artifact manifest | `workflow.aes_run` |
| Node and route progress | Logs plus simulated Workbench progress | `workflow.run_event` |
| Ollama calls | Component logs | `workflow.model_call` metadata and bounded content |
| Tool calls and results | `AgentState.tool_results` and logs | `workflow.tool_call` plus checkpoint snapshot |
| Artifact metadata | `manifest.json` in each run directory | `artifact.artifact` plus existing manifest |
| Artifact file bytes | Host-mounted `artifacts/` and provider workspaces | Remain outside PostgreSQL |
| Retrieval documents/index | Planned only | `retrieval.*` with `pgvector` |

Browser storage is no longer authoritative for identity. It remains the
temporary source of truth for conversations and active UI selection until the
chat schema and API slice is implemented. PostgreSQL is already authoritative
for users and sessions and will become authoritative for chats, progress, and
results in later slices.

## AgentState Persistence Map

`AgentState` remains the current-run contract. It should not grow into a user,
chat, or document database. The checkpointer stores complete state snapshots;
selected fields are also projected into queryable tables.

| `AgentState` group | Fields | Durable projection |
| --- | --- | --- |
| Request | `raw_user_input` | Triggering `chat_message.content`; optional immutable copy in `aes_run.input_text` |
| Intent | `request_intent`, `intent_reason` | `aes_run.request_intent`, `aes_run.intent_reason` |
| Problem extraction | `problem_class`, `domain_info`, `pde_info`, `coefficient_info`, `source_info`, `bc_info`, `initial_condition_info`, `time_info` | `aes_run.problem_snapshot` JSONB plus indexed `problem_class` and `pde_type` columns |
| Completeness | `missing_information`, `clarification_questions` | Checkpoint JSON; clarification assistant message; run status `waiting_for_user` |
| Formulation | `selected_formulation`, `validation_status`, `validation_errors` | `aes_run.formulation_snapshot` JSONB and validation status |
| Mode and recipe | `solution_mode`, `numerical_recipe_status`, `numerical_recipe`, `numerical_recipe_errors` | `aes_run.solution_mode`, recipe/status JSONB |
| Tool selection | `selected_tools`, `tool_execution_status` | `aes_run.selected_tools` JSONB and aggregate execution status |
| Tool execution | `tool_results`, `tool_errors` | One `tool_call` row per invocation; complete values also remain in checkpoints |
| Final response | `generated_artifact`, `agent_status`, `next_action` | Assistant `chat_message`, final `aes_run` status, response text, and next action |

Transport and ownership identifiers should be passed through the LangGraph
runtime configuration, not mixed into the mathematical state:

- `user_id`,
- `conversation_id`,
- `message_id`,
- `run_id`,
- LangGraph `thread_id` and `checkpoint_ns`,
- request/correlation ID.

The conversation ID should normally be the LangGraph `thread_id`. A separate
`run_id` identifies one user-message execution inside that thread.

## Graph Persistence Points

```mermaid
flowchart TD
    A["Workbench submits user message"] --> B["Persist chat_message"]
    B --> C["Create aes_run: created"]
    C --> D["Invoke graph with thread_id + run_id"]
    D --> E["Persist aes_run: running"]

    E --> N1["ingest / intent"]
    N1 --> CP1[("Checkpoint + run_event")]
    CP1 --> N2["classify / extract / completeness"]
    N2 --> CP2[("Checkpoint + run_event")]

    CP2 --> Q{"Clarification required?"}
    Q -->|yes| WAIT["Persist assistant question<br/>run: waiting_for_user"]
    WAIT --> END1["Return resumable thread"]

    Q -->|no| N3["formulation / validation / mode"]
    N3 --> CP3[("Checkpoint + run_event")]
    CP3 --> RET["Optional retrieval node/tool"]
    RET --> RH[("retrieval_query + retrieval_hit")]
    RH --> N4["recipe / tool selection"]
    N4 --> CP4[("Checkpoint + run_event")]

    CP4 --> TOOL["Execute selected tools"]
    TOOL --> TC[("tool_call rows")]
    TC --> STORE["Write artifact files"]
    STORE --> AM[("artifact metadata")]
    AM --> FINAL["Persist final run + assistant message"]
    FINAL --> END2["Return aes_result"]
```

Each node completion should create a small structured `run_event`. Complete
state recovery belongs to the checkpointer; `run_event` is the user-visible and
queryable timeline. This avoids storing a full state copy in every event row.

## Entity Model

```mermaid
erDiagram
    APP_USER ||--o{ AUTH_SESSION : has
    APP_USER ||--o{ CHAT_THREAD : owns
    CHAT_THREAD ||--o{ CHAT_MESSAGE : contains
    CHAT_THREAD ||--o{ AES_RUN : groups
    CHAT_MESSAGE ||--o| AES_RUN : triggers
    AES_RUN ||--o{ RUN_EVENT : records
    AES_RUN ||--o{ MODEL_CALL : invokes
    AES_RUN ||--o{ TOOL_CALL : invokes
    AES_RUN ||--o{ ARTIFACT : produces
    CHAT_THREAD ||--o{ LANGGRAPH_CHECKPOINT : resumes
    AES_RUN ||--o{ LANGGRAPH_CHECKPOINT : snapshots

    KNOWLEDGE_COLLECTION ||--o{ DOCUMENT : contains
    DOCUMENT ||--o{ DOCUMENT_CHUNK : splits_into
    DOCUMENT_CHUNK ||--o{ EMBEDDING : embeds
    AES_RUN ||--o{ RETRIEVAL_QUERY : performs
    RETRIEVAL_QUERY ||--o{ RETRIEVAL_HIT : returns
    DOCUMENT_CHUNK ||--o{ RETRIEVAL_HIT : matches

    APP_USER {
        uuid id PK
        string username UK
        string display_name
        string password_hash
        datetime created_at
        datetime disabled_at
    }

    AUTH_SESSION {
        uuid id PK
        uuid user_id FK
        string token_hash
        datetime created_at
        datetime expires_at
        datetime revoked_at
    }

    CHAT_THREAD {
        uuid id PK
        uuid user_id FK
        string title
        datetime created_at
        datetime updated_at
        datetime deleted_at
    }

    CHAT_MESSAGE {
        uuid id PK
        uuid thread_id FK
        string role
        text content
        jsonb metadata
        datetime created_at
    }

    AES_RUN {
        uuid id PK
        uuid thread_id FK
        uuid trigger_message_id FK
        string status
        string request_intent
        string problem_class
        string pde_type
        string solution_mode
        string next_action
        jsonb problem_snapshot
        jsonb formulation_snapshot
        jsonb numerical_recipe
        datetime created_at
        datetime started_at
        datetime finished_at
    }

    RUN_EVENT {
        uuid id PK
        uuid run_id FK
        int sequence_no
        string event_type
        string node_name
        string status
        jsonb payload
        datetime created_at
    }

    MODEL_CALL {
        uuid id PK
        uuid run_id FK
        string model
        string purpose
        string status
        int latency_ms
        int prompt_tokens
        int completion_tokens
        jsonb request_summary
        jsonb response_summary
        datetime created_at
    }

    TOOL_CALL {
        uuid id PK
        uuid run_id FK
        string tool_name
        string provider
        string status
        int attempt_no
        int latency_ms
        jsonb request_payload
        jsonb response_payload
        text error
        datetime started_at
        datetime finished_at
    }

    ARTIFACT {
        uuid id PK
        uuid run_id FK
        string name
        string kind
        string media_type
        string storage
        string status
        string uri
        string checksum_sha256
        bigint size_bytes
        jsonb metadata
        datetime created_at
    }

    LANGGRAPH_CHECKPOINT {
        string thread_id
        string checkpoint_ns
        string checkpoint_id
        jsonb metadata
        datetime created_at
    }

    KNOWLEDGE_COLLECTION {
        uuid id PK
        string name UK
        string description
        jsonb metadata
        datetime created_at
    }

    DOCUMENT {
        uuid id PK
        uuid collection_id FK
        string source_uri
        string title
        string checksum_sha256
        string status
        jsonb metadata
        datetime ingested_at
    }

    DOCUMENT_CHUNK {
        uuid id PK
        uuid document_id FK
        int chunk_index
        text content
        int token_count
        jsonb metadata
    }

    EMBEDDING {
        uuid id PK
        uuid chunk_id FK
        string model
        int dimensions
        vector embedding
        datetime created_at
    }

    RETRIEVAL_QUERY {
        uuid id PK
        uuid run_id FK
        text query_text
        string embedding_model
        jsonb filters
        datetime created_at
    }

    RETRIEVAL_HIT {
        uuid id PK
        uuid query_id FK
        uuid chunk_id FK
        float score
        int rank
    }
```

`LANGGRAPH_CHECKPOINT` is conceptual in this ER model. The implementation
should use the official PostgreSQL checkpointer's own tables and migrations
rather than reimplementing its storage format.

## Runtime Sequence

```mermaid
sequenceDiagram
    participant U as User
    participant W as web-ui
    participant A as AES API
    participant DB as PostgreSQL pgvector
    participant G as LangGraph
    participant L as Ollama
    participant R as Retrieval MCP
    participant F as FEniCS Runner
    participant S as Artifact Store

    U->>W: Send PDE request
    W->>A: Authenticated message request
    A->>DB: Insert chat_message and aes_run
    A->>G: Invoke with thread_id and run_id
    G->>DB: Save checkpoint and run events
    opt Grounding is required
        G->>R: Retrieve engineering context
        R->>DB: pgvector similarity search
        DB-->>R: Ranked document chunks
        R-->>G: Bounded context plus citations
    end
    G->>L: Structured extraction or code generation
    L-->>G: Model response
    G->>DB: Insert model_call metadata
    G->>F: Execute governed solve
    F-->>G: stdout, diagnostics, artifact references
    G->>DB: Insert tool_call result
    G->>S: Persist artifact files and manifest
    G->>DB: Insert artifact metadata and complete run
    G->>DB: Insert assistant chat_message
    G-->>A: Final aes_result
    A-->>W: Answer, run ID, and artifact links
```

## Run Lifecycle

```mermaid
stateDiagram-v2
    [*] --> created
    created --> running: graph starts
    running --> waiting_for_user: clarification or approval required
    waiting_for_user --> running: reply resumes same thread
    running --> completed: final response and artifacts committed
    running --> failed: unrecoverable node or tool error
    running --> cancelled: user or operator cancellation
    failed --> running: explicit retry creates a new attempt
    completed --> [*]
    cancelled --> [*]
```

The database should enforce valid statuses, but lifecycle transitions remain an
application responsibility. A retry should preserve the failed run and create
a new run or explicit attempt record rather than rewriting history.

## Implementation-Level Design

```mermaid
classDiagram
    class DatabaseSessionFactory {
        +transaction()
        +readSession()
    }

    class IdentityRepository {
        +createUser()
        +findUser()
        +createSession()
        +revokeSession()
    }

    class ConversationRepository {
        +listThreads()
        +createThread()
        +appendMessage()
        +loadThread()
    }

    class RunRepository {
        +createRun()
        +updateRunStatus()
        +appendEvent()
        +recordModelCall()
        +recordToolCall()
    }

    class ArtifactRepository {
        +registerArtifact()
        +listRunArtifacts()
    }

    class PostgresCheckpointStore {
        +setup()
        +getTuple()
        +put()
        +putWrites()
    }

    class RetrievalRepository {
        +upsertDocument()
        +storeChunks()
        +storeEmbeddings()
        +similaritySearch()
    }

    DatabaseSessionFactory <-- IdentityRepository
    DatabaseSessionFactory <-- ConversationRepository
    DatabaseSessionFactory <-- RunRepository
    DatabaseSessionFactory <-- ArtifactRepository
    DatabaseSessionFactory <-- PostgresCheckpointStore
    DatabaseSessionFactory <-- RetrievalRepository
```

These are responsibility boundaries, not a requirement for one large facade.
The LangGraph API should depend on small repositories and the official
checkpointer. Retrieval storage remains behind the Retrieval MCP provider.

## Retrieval Design

The retrieval MCP provider owns ingestion, chunking, embedding generation, and
similarity search. LangGraph decides when retrieval is useful and consumes only
bounded, cited results.

```mermaid
flowchart TD
    SRC["Engineering documents"] --> ING["Retrieval MCP ingestion"]
    ING --> DOC[("document + chunk metadata")]
    ING --> EMB["Embedding model"]
    EMB --> VEC[("pgvector embeddings")]

    Q["LangGraph retrieval request"] --> R["Typed retrieval MCP tool"]
    R --> VEC
    VEC --> HIT["Top-k chunks + scores + source metadata"]
    HIT --> CTX["retrieved context refs in current run"]
    CTX --> FORM["formulation / recipe / code prompt"]
```

Embedding records must include their model and dimension. A change of embedding
model creates a new embedding set; it must not silently mix incompatible
vectors in one index.

## Artifact Consistency

Artifact files and PostgreSQL cannot share one atomic transaction. Use this
order:

1. Create artifact metadata with status `materializing`.
2. Write the file to a temporary name in the artifact store.
3. Calculate size and SHA-256 checksum.
4. Atomically rename the file into its final run directory.
5. Mark metadata `stored` and commit the final URI.

Failed or interrupted writes remain queryable as `failed` or `missing` and can
be reconciled by a maintenance job. Provider-owned `mcp://` references remain
`referenced` until AES materializes them.

## Security And Privacy

- Store password hashes only, using a modern password-hashing algorithm; never
  store plaintext passwords or session tokens.
- Keep PostgreSQL on `ai-stack-net`. Do not publish its port in production.
- Use Docker secrets or an ignored environment file for credentials.
- Authorize every conversation, run, and artifact through `user_id` ownership.
- Redact secrets before persisting model/tool payloads.
- Store bounded model/tool content only when explicitly enabled. Metadata,
  hashes, timings, and statuses remain available without full prompt retention.
- Define retention periods for sessions, run events, checkpoints, model/tool
  payloads, and deleted chats.
- Raw container logs are not application database records. A future log system
  such as Loki or OpenTelemetry should store them separately.

## Target Project Layout

```text
database/
  architecture.md
  README.md
  compose.database.yaml
  migrations/
    apply.sh
    roles.sql
    versions/
      001_identity.sql
```

`deploy/compose.dev.yaml` and `deploy/compose.prod.yaml` include
`database/compose.database.yaml`, following the existing component-owned
Compose pattern. The one-shot `aes-database-migrate` service applies versioned
SQL before LangGraph starts.

## Implementation Phases

1. **Completed:** add the PostgreSQL/pgvector container, persistent volume,
   health check, secret configuration, migration job, schemas, and initial
   runtime roles.
2. **In progress:** server-side users and opaque sessions are implemented.
   Add conversations, messages, and run records, then migrate Workbench chat
   history from authoritative `localStorage` to API persistence.
3. Add the PostgreSQL LangGraph checkpointer and resume clarification using the
   existing conversation ID as `thread_id`.
4. Persist real graph node/route progress and stream it to the Workbench instead
   of simulating progress timers.
5. Add tool/model call records and artifact metadata registration.
6. Implement the Retrieval MCP ingestion/query path with pgvector and cited
   results.
7. Add backup, restore, retention, reconciliation, and database integration
   tests before treating the service as production-ready.

## Non-Goals For The First Database Step

- Storing XDMF, HDF5, VTK, PNG, SVG, MP4, generated Python, or raw logs as
  PostgreSQL large objects.
- Giving the browser direct SQL access.
- Replacing MCP with database calls from the LLM.
- Introducing Qdrant, Weaviate, Elasticsearch, or a second relational database
  before pgvector is measured under real AES retrieval workloads.
- Reimplementing the official LangGraph PostgreSQL checkpoint schema.
