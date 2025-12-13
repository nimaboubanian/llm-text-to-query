.PHONY: setup up down clean clean-all logs rebuild postgres mysql mongodb mariadb sqlserver clickhouse neo4j all help

# Default target - show help
help:
	@echo "Available commands:"
	@echo "  make setup      - Create all external volumes (run once)"
	@echo "  make up         - Start core services (ollama + app) in background"
	@echo "  make dev        - Start core services with logs in terminal"
	@echo "  make down       - Stop all services (keeps volumes)"
	@echo "  make clean      - Stop services, remove app containers & volumes"
	@echo "  make nuke       - Nuclear option: remove EVERYTHING"
	@echo "  make logs       - Follow app logs"
	@echo "  make rebuild    - Rebuild and restart app container"
	@echo "  make test       - Run tests in app container"
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
	@docker volume inspect llm_neo4j_logs >/dev/null 2>&1 || \
		(echo "Creating llm_neo4j_logs volume..." && docker volume create llm_neo4j_logs)
	@docker volume inspect llm_mongo_configdb >/dev/null 2>&1 || \
		(echo "Creating llm_mongo_configdb volume..." && docker volume create llm_mongo_configdb)
	@docker volume inspect llm_app_data >/dev/null 2>&1 || \
		(echo "Creating llm_app_data volume..." && docker volume create llm_app_data)

# Start core services
up: setup
	docker compose up -d

dev: setup
	docker compose up  # Without -d for logs in terminal

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

# Full cleanup - removes app containers, networks, AND volumes
clean:
	@echo "Stopping and removing all app containers..."
	docker compose down --remove-orphans --volumes
	@echo "Removing all app volumes..."
	-docker volume rm ollama_models llm_pg_data llm_mysql_data llm_mongo_data llm_mongo_configdb \
		llm_mariadb_data llm_sqlserver_data llm_clickhouse_data llm_neo4j_data llm_neo4j_logs llm_app_data 2>/dev/null || true
	@echo "Cleanup complete."

# Nuclear cleanup - removes EVERYTHING related to this project
nuke:
	@echo "🧨 Nuclear cleanup - removing all project containers, images, and volumes!"
	docker compose --profile all down --remove-orphans --volumes --rmi all
	-docker volume rm ollama_models llm_pg_data llm_mysql_data llm_mongo_data llm_mongo_configdb \
		llm_mariadb_data llm_sqlserver_data llm_clickhouse_data llm_neo4j_data llm_neo4j_logs llm_app_data 2>/dev/null || true
	-docker network rm llm-text-to-query_app-network 2>/dev/null || true
	@echo "💥 All project resources removed. Run 'make setup' to start fresh."

# View app logs
logs:
	docker compose logs app

# Rebuild app container
rebuild:
	docker compose build app
	docker compose up -d app

test:
	docker compose exec app pytest
