\set ON_ERROR_STOP on

SELECT 'CREATE ROLE aes_app LOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aes_app')
\gexec

ALTER ROLE aes_app LOGIN PASSWORD :'app_password';

SELECT 'CREATE ROLE aes_checkpoint NOLOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aes_checkpoint')
\gexec

SELECT 'CREATE ROLE aes_retrieval NOLOGIN'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'aes_retrieval')
\gexec

