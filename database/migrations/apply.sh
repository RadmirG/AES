#!/bin/sh
set -eu

: "${PGHOST:?PGHOST is required}"
: "${PGDATABASE:?PGDATABASE is required}"
: "${PGUSER:?PGUSER is required}"
: "${PGPASSWORD:?PGPASSWORD is required}"
: "${AES_POSTGRES_APP_PASSWORD:?AES_POSTGRES_APP_PASSWORD is required}"

psql_admin() {
    psql \
        --set=ON_ERROR_STOP=1 \
        --host="$PGHOST" \
        --port="${PGPORT:-5432}" \
        --dbname="$PGDATABASE" \
        --username="$PGUSER" \
        "$@"
}

echo "database | applying runtime roles"
psql_admin \
    --set=app_password="$AES_POSTGRES_APP_PASSWORD" \
    --file=/migrations/roles.sql

psql_admin <<'SQL'
CREATE TABLE IF NOT EXISTS public.aes_schema_migration (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

for migration in /migrations/versions/*.sql; do
    [ -f "$migration" ] || continue
    version="$(basename "$migration")"
    safe_version="$(printf '%s' "$version" | sed "s/'/''/g")"
    applied="$(
        psql_admin --tuples-only --no-align \
            --command="SELECT 1 FROM public.aes_schema_migration WHERE version = '$safe_version';"
    )"

    if [ "$applied" = "1" ]; then
        echo "database | migration already applied | $version"
        continue
    fi

    echo "database | applying migration | $version"
    psql_admin \
        --single-transaction \
        --file="$migration" \
        --command="INSERT INTO public.aes_schema_migration(version) VALUES ('$safe_version');"
done

echo "database | migrations complete"
