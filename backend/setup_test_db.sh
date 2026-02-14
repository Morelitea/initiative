#!/bin/bash
# Setup script for test database

set -e

echo "Setting up test database..."

# Database configuration from .env
DB_USER="initiative"
DB_PASSWORD="initiative"
DB_NAME="initiative_test"
DB_HOST="localhost"
DB_PORT="5432"
DOCKER_CONTAINER="initiative-db"

# Drop and recreate the test database using docker exec
echo "Dropping existing test database if it exists..."
docker exec -e PGPASSWORD=$DB_PASSWORD $DOCKER_CONTAINER psql -U $DB_USER -d postgres -c "DROP DATABASE IF EXISTS $DB_NAME;" 2>/dev/null || true

echo "Creating test database..."
docker exec -e PGPASSWORD=$DB_PASSWORD $DOCKER_CONTAINER psql -U $DB_USER -d postgres -c "CREATE DATABASE $DB_NAME;"

echo "Running Alembic migrations on test database..."
# Temporarily set DATABASE_URL to point to test database
export DATABASE_URL="postgresql+asyncpg://$DB_USER:$DB_PASSWORD@$DB_HOST:$DB_PORT/$DB_NAME"
alembic upgrade head

echo "✓ Test database setup complete!"
echo "Database: $DB_NAME"
echo "You can now run tests with: python3 -m pytest app/"
