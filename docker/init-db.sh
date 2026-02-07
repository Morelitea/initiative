#!/bin/bash
# PostgreSQL init script - mounted to /docker-entrypoint-initdb.d/
# Creates app_user (RLS-enforced) and app_admin (BYPASSRLS) roles.
#
# Environment variables (set in docker-compose):
#   APP_USER_PASSWORD - password for the app_user role
#   APP_ADMIN_PASSWORD - password for the app_admin role
#   POSTGRES_DB - database name (provided by postgres image)

set -e

# Use defaults if passwords not provided
APP_USER_PASSWORD="${APP_USER_PASSWORD:-app_user_password}"
APP_ADMIN_PASSWORD="${APP_ADMIN_PASSWORD:-app_admin_password}"

echo "Creating app_user role (RLS-enforced)..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v app_user_pw="$APP_USER_PASSWORD" <<-'EOSQL'
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
            EXECUTE format('CREATE ROLE app_user WITH LOGIN NOINHERIT PASSWORD %L', :'app_user_pw');
        END IF;
    END
    $$;

    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_user;
EOSQL

echo "Creating app_admin role (BYPASSRLS)..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    -v app_admin_pw="$APP_ADMIN_PASSWORD" <<-'EOSQL'
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_admin') THEN
            EXECUTE format('CREATE ROLE app_admin WITH LOGIN BYPASSRLS PASSWORD %L', :'app_admin_pw');
        END IF;
    END
    $$;

    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO app_admin;
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO app_admin;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO app_admin;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO app_admin;
EOSQL

echo "Database roles created successfully."
