CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS chat;
CREATE SCHEMA IF NOT EXISTS workflow;
CREATE SCHEMA IF NOT EXISTS checkpoint;
CREATE SCHEMA IF NOT EXISTS artifact;
CREATE SCHEMA IF NOT EXISTS retrieval;

CREATE TABLE identity.app_user (
    id uuid PRIMARY KEY,
    username varchar(64) NOT NULL UNIQUE,
    display_name varchar(120) NOT NULL,
    password_hash text NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    disabled_at timestamptz,
    CONSTRAINT app_user_username_normalized CHECK (username = lower(username)),
    CONSTRAINT app_user_status_valid CHECK (status IN ('active', 'disabled'))
);

CREATE TABLE identity.auth_session (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES identity.app_user(id) ON DELETE CASCADE,
    token_hash char(64) NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    revoked_at timestamptz
);

CREATE INDEX auth_session_user_id_idx
    ON identity.auth_session(user_id);

CREATE INDEX auth_session_active_expiry_idx
    ON identity.auth_session(expires_at)
    WHERE revoked_at IS NULL;

GRANT USAGE ON SCHEMA identity, chat, workflow, artifact TO aes_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA identity TO aes_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA identity
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO aes_app;

GRANT USAGE ON SCHEMA checkpoint TO aes_checkpoint;
GRANT USAGE ON SCHEMA retrieval TO aes_retrieval;

