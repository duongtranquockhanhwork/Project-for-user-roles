-- Creates the least-privilege application role. Executed once by the official
-- postgres image on first start (docker-entrypoint-initdb.d), before schema.sql.
-- The password is read from the APP_DB_PASSWORD environment variable with
-- psql's \getenv, so it is never stored in the repository.
--
-- This is a .sql file (not a .sh script) on purpose: .sh init scripts depend on
-- the file's executable bit, which is lost or misreported on some hosts
-- (macOS/Linux checkouts, archives created on Windows) and then breaks the
-- whole database initialisation. A .sql file runs the same way everywhere.
\set ON_ERROR_STOP on
\getenv app_pw APP_DB_PASSWORD
\if :{?app_pw}
\else
DO $$ BEGIN RAISE EXCEPTION 'APP_DB_PASSWORD is not set'; END $$;
\endif
SELECT current_database() AS db \gset

CREATE ROLE uni_app LOGIN PASSWORD :'app_pw'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    CONNECTION LIMIT 40;
REVOKE CONNECT ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO uni_app;
