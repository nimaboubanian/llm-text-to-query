"""Main Streamlit application for LLM Text-to-Query chatbot."""

import os
import re

import pandas as pd
import requests
import streamlit as st
from sqlalchemy import text

from .database_config import (
    DatabaseConfigManager,
    DatabaseType,
    build_connection_url,
    discover_available_servers,
    get_server_databases,
)
from .schema_helper import (
    create_engine_for_database,
    get_database_schema_string,
    validate_database_connection,
)

# Environment Variables
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")


def get_sql_from_llm(
    user_query, schema_str, db_type: DatabaseType = DatabaseType.POSTGRESQL
):
    """Sends the prompt to Ollama and returns the generated SQL."""

    # Map database types to SQL dialects
    dialect_map = {
        DatabaseType.POSTGRESQL: "PostgreSQL",
        DatabaseType.MYSQL: "MySQL",
        DatabaseType.MARIADB: "MariaDB (MySQL-compatible)",
        DatabaseType.SQLITE: "SQLite",
        DatabaseType.MONGODB: "MongoDB (use MongoDB query syntax, not SQL)",
        DatabaseType.SQLSERVER: "Microsoft SQL Server (T-SQL)",
        DatabaseType.CLICKHOUSE: "ClickHouse SQL",
        DatabaseType.NEO4J: "Neo4j Cypher (graph query language, not SQL)",
    }
    dialect = dialect_map.get(db_type, "SQL")

    prompt = (
        f"You are a {dialect} query generator. "
        f"Given the following database schema:\n{schema_str}\n\n"
        f"Generate a query to answer: {user_query}\n\n"
        f"Rules:\n"
        f"- Return ONLY the query, nothing else\n"
        f"- No explanations, no comments, no markdown\n"
        f"- Only use tables and columns from the schema above\n"
        f"- Use {dialect} syntax"
    )

    payload = {"model": "qwen2.5:7b", "prompt": prompt, "stream": False}

    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate", json=payload, timeout=120
        )

        if response.status_code == 404:
            return (
                None,
                "Model 'qwen2.5:7b' not found. "
                "Please run: docker exec ollama-model-init ollama pull qwen2.5:7b",
            )

        if response.status_code != 200:
            return None, f"LLM API error: {response.status_code} - {response.text}"

        response_json = response.json()
        sql_query = response_json.get("response", "").strip()

        if not sql_query:
            return None, "LLM returned an empty response"

        # Clean SQL query - extract only the first SQL statement
        sql_query = clean_sql_response(sql_query)

        if not sql_query:
            return None, "Could not extract a valid SQL query from LLM response"

        return sql_query, None

    except requests.exceptions.Timeout:
        return (
            None,
            "LLM request timed out. The model might be loading, please try again.",
        )
    except requests.exceptions.RequestException as e:
        return None, f"Failed to connect to LLM: {e}"


def clean_sql_response(response):
    """Extract clean SQL from LLM response that may contain markdown or explanations."""
    # Remove markdown code blocks
    # Match ```sql ... ``` or ``` ... ```
    code_block_pattern = r"```(?:sql)?\s*(.*?)```"
    matches = re.findall(code_block_pattern, response, re.DOTALL | re.IGNORECASE)
    if matches:
        # Take the first code block
        return matches[0].strip()

    # If no code blocks, try to extract SELECT/INSERT/UPDATE/DELETE statement
    # Find the first SQL statement
    sql_pattern = r"(SELECT|INSERT|UPDATE|DELETE|WITH)\s+.*?;"
    match = re.search(sql_pattern, response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0).strip()

    # If no semicolon, try without it
    sql_pattern_no_semi = r"(SELECT|INSERT|UPDATE|DELETE|WITH)\s+[^;]*"
    match = re.search(sql_pattern_no_semi, response, re.DOTALL | re.IGNORECASE)
    if match:
        sql = match.group(0).strip()
        # Stop at common non-SQL patterns
        for stop_word in ["\n\nOR ", "\n\nNote:", "\n\nThis ", "\n\nIf ", "\n\n--"]:
            if stop_word in sql:
                sql = sql.split(stop_word)[0].strip()
        return sql

    # Last resort: return the first line if it looks like SQL
    first_line = response.split("\n")[0].strip()
    if first_line.upper().startswith(("SELECT", "INSERT", "UPDATE", "DELETE", "WITH")):
        return first_line

    return None


def execute_sql_query(engine, sql_query, db_type: DatabaseType):
    """Executes the SQL query and returns a DataFrame."""
    try:
        # SQL-based databases (SQLAlchemy)
        sql_types = [
            DatabaseType.POSTGRESQL,
            DatabaseType.MYSQL,
            DatabaseType.SQLITE,
            DatabaseType.MARIADB,
            DatabaseType.SQLSERVER,
            DatabaseType.CLICKHOUSE,
        ]
        if db_type in sql_types:
            with engine.connect() as conn:
                result = conn.execute(text(sql_query))
                rows = result.fetchall()
                columns = result.keys()
                df = pd.DataFrame(rows, columns=columns)
                return df
        elif db_type == DatabaseType.MONGODB:
            # For MongoDB, the query would be different (not SQL)
            return "MongoDB query execution not yet implemented"
        elif db_type == DatabaseType.NEO4J:
            # Neo4j uses Cypher, handle separately
            return _execute_neo4j_query(engine, sql_query)
        else:
            return f"Query execution not supported for {db_type.value}"
    except Exception as e:  # pylint: disable=broad-exception-caught
        return str(e)


def _execute_neo4j_query(connection_url: str, cypher_query: str):
    """Execute a Cypher query on Neo4j and return results as DataFrame."""
    try:
        from neo4j import GraphDatabase  # pylint: disable=import-outside-toplevel

        # Parse bolt URL: bolt://user:pass@host:port
        url_parts = connection_url.replace("bolt://", "").split("@")
        auth = (
            tuple(url_parts[0].split(":")) if len(url_parts) > 1 else ("neo4j", "neo4j")
        )
        uri = f"bolt://{url_parts[-1]}"

        driver = GraphDatabase.driver(uri, auth=auth)
        with driver.session() as session:
            result = session.run(cypher_query)
            records = [dict(record) for record in result]
            driver.close()

            if records:
                return pd.DataFrame(records)
            return pd.DataFrame()
    except ImportError:
        return "Neo4j support requires 'neo4j' package."
    except Exception as e:  # pylint: disable=broad-exception-caught
        return str(e)


def init_session_state():
    """Initialize all session state variables with defaults."""
    defaults = {
        "db_config_manager": DatabaseConfigManager(),
        "selected_db_key": None,
        "current_engine": None,
        "current_schema": None,
        "manual_schema_override": None,
        "use_manual_schema": False,
        "chat_history": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    # Set default selected database if not set
    if st.session_state.selected_db_key is None:
        all_dbs = st.session_state.db_config_manager.get_all_databases()
        if all_dbs:
            st.session_state.selected_db_key = list(all_dbs.keys())[0]


def main():  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    """Main Streamlit application."""
    # Page Config (must be first Streamlit command)
    st.set_page_config(page_title="Text-to-SQL Chatbot", layout="wide")

    # Initialize session state
    init_session_state()

    # --- Sidebar ---
    st.sidebar.title("⚙️ Database Settings")

    # Database Selection Section
    st.sidebar.subheader("📊 Select Database")

    db_config_manager = st.session_state.db_config_manager
    all_databases = db_config_manager.get_all_databases()

    if all_databases:
        db_display_names = db_config_manager.get_database_display_names()
        db_keys = [key for key, _ in db_display_names]
        db_labels = [
            f"{name} ({all_databases[key].db_type.value})"
            for key, name in db_display_names
        ]

        # Find current selection index
        current_index = 0
        if st.session_state.selected_db_key in db_keys:
            current_index = db_keys.index(st.session_state.selected_db_key)

        selected_index = st.sidebar.selectbox(
            "Choose Database",
            range(len(db_labels)),
            format_func=lambda i: db_labels[i],
            index=current_index,
            key="db_selector",
        )

        new_selected_key = db_keys[selected_index]

        # If database changed, update engine and schema
        if new_selected_key != st.session_state.selected_db_key:
            st.session_state.selected_db_key = new_selected_key
            st.session_state.current_engine = None
            st.session_state.current_schema = None
            st.session_state.use_manual_schema = False
            st.rerun()
    else:
        st.sidebar.warning("⚠️ No databases configured")

    # Quick Connect - Discover available servers and databases
    st.sidebar.subheader("⚡ Quick Connect")

    # Cache discovered servers for this session
    if "discovered_servers" not in st.session_state:
        st.session_state.discovered_servers = discover_available_servers()

    servers = st.session_state.discovered_servers

    if servers:
        # Step 1: Select server
        server_names = ["-- Select server --"] + [
            f"{s.name} ({s.host}:{s.port})" for s in servers
        ]
        selected_server_name = st.sidebar.selectbox(
            "Database Server", options=server_names, key="quick_connect_server"
        )

        if selected_server_name != "-- Select server --":
            # Find selected server
            server_idx = server_names.index(selected_server_name) - 1
            selected_server = servers[server_idx]

            # Step 2: List databases on this server
            cache_key = f"dbs_{selected_server.host}_{selected_server.port}"
            if cache_key not in st.session_state:
                st.session_state[cache_key] = get_server_databases(selected_server)

            databases = st.session_state[cache_key]

            if databases:
                selected_database = st.sidebar.selectbox(
                    "Database/Schema", options=databases, key="quick_connect_database"
                )

                # Build connection URL
                connection_url = build_connection_url(
                    selected_server, selected_database
                )
                display_name = f"{selected_database} ({selected_server.name})"

                if st.sidebar.button("Connect", key="quick_connect_btn"):
                    # Check if already added
                    existing_key = None
                    for key, config in all_databases.items():
                        if config.url == connection_url:
                            existing_key = key
                            break

                    if existing_key:
                        st.session_state.selected_db_key = existing_key
                        st.sidebar.info("Already added, selected it.")
                    else:
                        config_key = db_config_manager.add_database(
                            display_name, selected_server.db_type, connection_url
                        )
                        st.session_state.selected_db_key = config_key
                        st.sidebar.success("✅ Connected!")
                    st.rerun()
            else:
                st.sidebar.warning("No databases found on this server")

        if st.sidebar.button("🔄 Refresh", key="refresh_servers"):
            # Clear all cached data
            keys_to_clear = [k for k in st.session_state if k.startswith("dbs_")]
            for k in keys_to_clear:
                del st.session_state[k]
            st.session_state.discovered_servers = discover_available_servers()
            st.rerun()
    else:
        st.sidebar.info(
            "No database servers detected. Start containers or add manually."
        )
        if st.sidebar.button("🔄 Scan", key="scan_servers"):
            st.session_state.discovered_servers = discover_available_servers()
            st.rerun()

    # Manual Database Connection Section
    st.sidebar.subheader("➕ Add Manually")

    with st.sidebar.expander("Custom Database Connection"):
        custom_db_name = st.text_input("Database Name", key="custom_db_name")
        custom_db_type = st.selectbox(
            "Database Type",
            options=[db_type.value for db_type in DatabaseType],
            key="custom_db_type",
        )
        custom_db_url = st.text_input(
            "Connection URL",
            placeholder="postgresql://user:pass@host:port/dbname",
            key="custom_db_url",
        )
        custom_db_desc = st.text_area("Description (optional)", key="custom_db_desc")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Test", key="test_conn"):
                if custom_db_url:
                    db_type_enum = DatabaseType[custom_db_type.upper().replace(" ", "")]
                    success, error = validate_database_connection(
                        custom_db_url, db_type_enum
                    )
                    if success:
                        st.success("✅ OK")
                    else:
                        st.error(f"❌ {error}")
                else:
                    st.warning("Enter URL")

        with col2:
            if st.button("Add", key="add_db"):
                if custom_db_name and custom_db_url:
                    db_type_enum = DatabaseType[custom_db_type.upper().replace(" ", "")]
                    success, error = validate_database_connection(
                        custom_db_url, db_type_enum
                    )
                    if success:
                        config_key = db_config_manager.add_database(
                            custom_db_name, db_type_enum, custom_db_url, custom_db_desc
                        )
                        st.session_state.selected_db_key = config_key
                        st.success("✅ Added")
                        st.rerun()
                    else:
                        st.error(f"❌ {error}")
                else:
                    st.warning("Name & URL required")

    # Schema Management Section
    st.sidebar.subheader("📋 Schema Management")

    schema_mode = st.sidebar.radio(
        "Schema Source",
        options=["Auto-introspect", "Manual Override"],
        index=0 if not st.session_state.use_manual_schema else 1,
        key="schema_mode",
    )

    if schema_mode == "Manual Override":
        st.session_state.use_manual_schema = True
        manual_schema = st.sidebar.text_area(
            "Enter Schema Manually",
            value=st.session_state.manual_schema_override or "",
            height=200,
            key="manual_schema_input",
        )
        if st.sidebar.button("Apply Manual Schema"):
            st.session_state.manual_schema_override = manual_schema
            st.success("✅ Manual schema applied")
    else:
        st.session_state.use_manual_schema = False
        if st.sidebar.button("Refresh Schema"):
            st.session_state.current_schema = None
            st.rerun()

    # Other Settings
    st.sidebar.subheader("🔧 Other Settings")
    if st.sidebar.button("Reset Chat History"):
        st.session_state.chat_history = []
        st.rerun()

    # --- Main Chat Interface ---
    st.title("💬 Text-to-SQL Chatbot")

    # Get current database config
    current_db_config = None
    if st.session_state.selected_db_key:
        current_db_config = db_config_manager.get_database(
            st.session_state.selected_db_key
        )

    if not current_db_config:
        st.error("❌ No database selected. Please configure a database in the sidebar.")
        return

    # Display current database info
    st.info(
        f"🗄️ **Connected to:** {current_db_config.name} ({current_db_config.db_type.value})"
    )

    # Initialize engine if not already done
    if st.session_state.current_engine is None:
        try:
            with st.spinner(f"Connecting to {current_db_config.name}..."):
                st.session_state.current_engine = create_engine_for_database(
                    current_db_config.url, current_db_config.db_type
                )
        except Exception as e:  # pylint: disable=broad-exception-caught
            st.error(f"❌ Failed to connect to database: {e}")
            return

    # Get or refresh schema
    if (
        st.session_state.current_schema is None
        and not st.session_state.use_manual_schema
    ):
        try:
            with st.spinner("Introspecting database schema..."):
                st.session_state.current_schema = get_database_schema_string(
                    st.session_state.current_engine, current_db_config.db_type
                )
        except Exception as e:  # pylint: disable=broad-exception-caught
            st.error(f"❌ Could not fetch database schema: {e}")
            return

    # Determine which schema to use
    active_schema = (
        st.session_state.manual_schema_override
        if st.session_state.use_manual_schema
        and st.session_state.manual_schema_override
        else st.session_state.current_schema
    )

    if not active_schema:
        st.warning("⚠️ No schema available. Please configure schema in sidebar.")
        return

    # Show schema preview
    with st.expander("📋 View Current Schema"):
        st.code(active_schema, language="sql")

    # Display chat history
    for entry in st.session_state.chat_history:
        with st.chat_message(entry["role"]):
            st.write(entry["content"])
            if "sql" in entry:
                with st.expander("SQL Query"):
                    st.code(entry["sql"], language="sql")
            if "dataframe" in entry:
                st.dataframe(entry["dataframe"])

    # Chat input
    query = st.chat_input("Ask a question about the database...")

    if query:
        # Display user message
        with st.chat_message("user"):
            st.write(query)
        st.session_state.chat_history.append({"role": "user", "content": query})

        # Generate SQL
        with st.spinner("Generating SQL..."):
            generated_sql, error = get_sql_from_llm(
                query, active_schema, current_db_config.db_type
            )

        if error:
            # Handle LLM error
            with st.chat_message("assistant"):
                st.error(f"❌ {error}")
            st.session_state.chat_history.append(
                {"role": "assistant", "content": f"Error: {error}"}
            )
        else:
            # Execute query
            result = execute_sql_query(
                st.session_state.current_engine,
                generated_sql,
                current_db_config.db_type,
            )

            # Display assistant response
            with st.chat_message("assistant"):
                with st.expander("Generated SQL Query", expanded=True):
                    st.code(generated_sql, language="sql")

                if isinstance(result, pd.DataFrame):
                    st.write("Here is the result of your query:")
                    st.dataframe(result)
                    st.session_state.chat_history.append(
                        {
                            "role": "assistant",
                            "content": "Here is the result of your query:",
                            "sql": generated_sql,
                            "dataframe": result,
                        }
                    )
                else:
                    st.error(f"Error executing SQL: {result}")
                    st.session_state.chat_history.append(
                        {
                            "role": "assistant",
                            "content": f"Error executing SQL: {result}",
                            "sql": generated_sql,
                        }
                    )


if __name__ == "__main__":
    main()
