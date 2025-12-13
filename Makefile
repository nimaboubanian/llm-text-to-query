.PHONY: setup up down clean clean-all logs rebuild postgres mysql mongodb mariadb sqlserver clickhouse neo4j all help

# Default target - show help
help:
	@echo "Available commands:"
	@echo "  make setup      - Create all external volumes (run once)"
	@echo "  make up         - Start core services (ollama + app)"
	@echo "  make down       - Stop all services (keeps volumes)"
	@echo "  make clean      - Stop services only"
	@echo "  make clean-all  - Stop and remove ALL external volumes"
	@echo "  make logs       - Follow app logs"
	@echo "  make rebuild    - Rebuild and restart app container"
	@echo ""
	@echo "Database profiles:"
	@echo "  make postgres   - Start with PostgreSQL"
	@echo "  make mysql      - Start with MySQL"
	@echo "  make mongodb    - Start with MongoDB"
	@echo "  make mariadb    - Start with MariaDB"
	@echo "  make sqlserver  - Start with SQL Server"
	@echo "  make clickhouse - Start with ClickHouse"
	@echo "  make neo4j      - Start with Neo4j"
	@echo "  make all        - Start with all databases"

# Create external volumes if they don't exist
setup:
	@docker volume inspect ollama_models >/dev/null 2>&1 || \
		(echo "Creating ollama_models volume..." && docker volume create ollama_models)
	@docker volume inspect llm_pg_data >/dev/null 2>&1 || \
		(echo "Creating llm_pg_data volume..." && docker volume create llm_pg_data)
	@docker volume inspect llm_mysql_data >/dev/null 2>&1 || \
		(echo "Creating llm_mysql_data volume..." && docker volume create llm_mysql_data)
	@docker volume inspect llm_mongo_data >/dev/null 2>&1 || \
		(echo "Creating llm_mongo_data volume..." && docker volume create llm_mongo_data)
	@docker volume inspect llm_mariadb_data >/dev/null 2>&1 || \
		(echo "Creating llm_mariadb_data volume..." && docker volume create llm_mariadb_data)
	@docker volume inspect llm_sqlserver_data >/dev/null 2>&1 || \
		(echo "Creating llm_sqlserver_data volume..." && docker volume create llm_sqlserver_data)
	@docker volume inspect llm_clickhouse_data >/dev/null 2>&1 || \
		(echo "Creating llm_clickhouse_data volume..." && docker volume create llm_clickhouse_data)
	@docker volume inspect llm_neo4j_data >/dev/null 2>&1 || \
		(echo "Creating llm_neo4j_data volume..." && docker volume create llm_neo4j_data)
	@docker volume inspect llm_app_data >/dev/null 2>&1 || \
		(echo "Creating llm_app_data volume..." && docker volume create llm_app_data)

# Start core services
up: setup
	docker compose up -d

# Database profile targets
postgres: setup
	docker compose --profile postgres up -d

mysql: setup
	docker compose --profile mysql up -d

mongodb: setup
	docker compose --profile mongodb up -d

mariadb: setup
	docker compose --profile mariadb up -d

sqlserver: setup
	docker compose --profile sqlserver up -d

clickhouse: setup
	docker compose --profile clickhouse up -d

neo4j: setup
	docker compose --profile neo4j up -d

all: setup
	docker compose --profile all up -d

# Stop services (keeps volumes)
down:
	docker compose down

# Stop services only (alias for down)
clean:
	docker compose down

# Full cleanup - removes ALL external volumes
clean-all:
	docker compose down
	@echo "Removing all external volumes..."
	-docker volume rm ollama_models llm_pg_data llm_mysql_data llm_mongo_data \
		llm_mariadb_data llm_sqlserver_data llm_clickhouse_data llm_neo4j_data llm_app_data 2>/dev/null || true
	@echo "All volumes removed."

# View app logs
logs:
	docker compose logs -f app

# Rebuild app container
rebuild:
	docker compose build app
	docker compose up -d app
