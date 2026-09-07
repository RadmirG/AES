CREATE TABLE workflow.aes_run (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES identity.app_user(id) ON DELETE CASCADE,
    conversation_id varchar(160) NOT NULL,
    request_fingerprint char(64) NOT NULL,
    request jsonb NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'queued',
    progress jsonb NOT NULL DEFAULT '[]'::jsonb,
    response jsonb,
    error text,
    worker_id uuid,
    heartbeat_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    CONSTRAINT aes_run_status_valid CHECK (
        status IN ('queued', 'running', 'completed', 'failed', 'interrupted')
    )
);

CREATE INDEX aes_run_user_conversation_idx
    ON workflow.aes_run(user_id, conversation_id, created_at DESC);
CREATE INDEX aes_run_queue_idx ON workflow.aes_run(created_at) WHERE status = 'queued';
CREATE INDEX aes_run_heartbeat_idx ON workflow.aes_run(heartbeat_at) WHERE status = 'running';
GRANT SELECT, INSERT, UPDATE, DELETE ON workflow.aes_run TO aes_app;
