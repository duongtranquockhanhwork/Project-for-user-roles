#!/bin/sh
# Creates the least-privilege application role. Executed once by the official
# postgres image on first start (docker-entrypoint-initdb.d), before schema.sql.
# The password is read from the APP_DB_PASSWORD environment variable, so it is
# never stored in the repository.
set -eu

if [ -z "${APP_DB_PASSWORD:-}" ]; then
    echo "APP_DB_PASSWORD is not set" >&2
    exit 1
fi

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_pw="$APP_DB_PASSWORD" -v db="$POSTGRES_DB" <<'EOSQL'
CREATE ROLE uni_app LOGIN PASSWORD :'app_pw'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    CONNECTION LIMIT 40;
REVOKE CONNECT ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO uni_app;
EOSQL
