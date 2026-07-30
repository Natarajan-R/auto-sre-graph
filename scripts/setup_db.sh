#!/bin/bash
# scripts/setup_db.sh
# Database setup script for Auto-SRE-Graph

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Auto-SRE-Graph Database Setup${NC}"
echo -e "${GREEN}========================================${NC}"

# Load environment variables
if [ -f .env ]; then
    echo -e "${YELLOW}Loading environment from .env file${NC}"
    export $(cat .env | grep -v '^#' | xargs)
else
    echo -e "${YELLOW}No .env file found, using default values${NC}"
fi

# Default values
POSTGRES_HOST=${POSTGRES_HOST:-localhost}
POSTGRES_PORT=${POSTGRES_PORT:-5432}
POSTGRES_DATABASE=${POSTGRES_DATABASE:-sre_workflows}
POSTGRES_USER=${POSTGRES_USER:-postgres}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-postgres}

echo -e "${YELLOW}Configuration:${NC}"
echo "  Host: $POSTGRES_HOST"
echo "  Port: $POSTGRES_PORT"
echo "  Database: $POSTGRES_DATABASE"
echo "  User: $POSTGRES_USER"
echo ""

# Check if PostgreSQL is running
echo -e "${YELLOW}Checking PostgreSQL connection...${NC}"
if ! PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d postgres -c "SELECT 1" > /dev/null 2>&1; then
    echo -e "${RED}Error: Cannot connect to PostgreSQL${NC}"
    echo "Please ensure PostgreSQL is running and accessible."
    exit 1
fi
echo -e "${GREEN}✓ PostgreSQL connection successful${NC}"

# Check if database exists
echo -e "${YELLOW}Checking if database exists...${NC}"
DB_EXISTS=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$POSTGRES_DATABASE'")

if [ "$DB_EXISTS" = "1" ]; then
    echo -e "${YELLOW}Database '$POSTGRES_DATABASE' already exists${NC}"
    read -p "Drop and recreate? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Dropping database...${NC}"
        PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d postgres -c "DROP DATABASE IF EXISTS $POSTGRES_DATABASE"
        echo -e "${GREEN}✓ Database dropped${NC}"
    else
        echo -e "${YELLOW}Using existing database${NC}"
    fi
fi

# Create database if it doesn't exist
echo -e "${YELLOW}Creating database...${NC}"
PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d postgres -c "CREATE DATABASE $POSTGRES_DATABASE"
echo -e "${GREEN}✓ Database created${NC}"

# Enable vector extension
echo -e "${YELLOW}Enabling pgvector extension...${NC}"
PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -c "CREATE EXTENSION IF NOT EXISTS vector"
echo -e "${GREEN}✓ pgvector extension enabled${NC}"

# Run migration scripts
echo -e "${YELLOW}Running migration scripts...${NC}"

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS_DIR="$SCRIPT_DIR/../migrations"

# Run main init.sql
if [ -f "$MIGRATIONS_DIR/init.sql" ]; then
    echo -e "${YELLOW}Executing init.sql...${NC}"
    PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -f "$MIGRATIONS_DIR/init.sql"
    echo -e "${GREEN}✓ init.sql executed${NC}"
else
    echo -e "${RED}Error: init.sql not found at $MIGRATIONS_DIR/init.sql${NC}"
    exit 1
fi

# Run any additional migration files
for migration in "$MIGRATIONS_DIR"/[0-9]*.sql; do
    if [ -f "$migration" ]; then
        echo -e "${YELLOW}Executing $(basename "$migration")...${NC}"
        PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -f "$migration"
        echo -e "${GREEN}✓ $(basename "$migration") executed${NC}"
    fi
done

# Create application user if not exists
echo -e "${YELLOW}Creating application user...${NC}"
PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_user WHERE usename = 'sre_app_user') THEN
        CREATE USER sre_app_user WITH PASSWORD 'sre_app_password_please_change_in_production';
    END IF;
END
\$\$;
GRANT CONNECT ON DATABASE $POSTGRES_DATABASE TO sre_app_user;
GRANT USAGE ON SCHEMA public TO sre_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sre_app_user;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO sre_app_user;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO sre_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sre_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO sre_app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO sre_app_user;
EOF
echo -e "${GREEN}✓ Application user created${NC}"

# Verify setup
echo -e "${YELLOW}Verifying database setup...${NC}"
TABLE_COUNT=$(PGPASSWORD=$POSTGRES_PASSWORD psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DATABASE -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'")

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}✓ Database setup completed successfully!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "${YELLOW}Summary:${NC}"
echo "  Database: $POSTGRES_DATABASE"
echo "  Tables: $TABLE_COUNT"
echo "  Application User: sre_app_user"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "  1. Update .env file with your database credentials"
echo "  2. Run seed_data.py to load sample data"
echo "  3. Start the application: make dev"
echo ""