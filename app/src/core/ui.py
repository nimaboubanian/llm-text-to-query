"""Streamlit UI components for the Text-to-Query chatbot."""

import pandas as pd
import streamlit as st

try:
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
except ImportError:
    from database_config import (
        DatabaseConfigManager,
        DatabaseType,
        build_connection_url,
        discover_available_servers,
        get_server_databases,
    )
    from schema_helper import (
        create_engine_for_database,
        get_database_schema_string,
        validate_database_connection,
    )


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


def render_database_selector():
    """Render the database selection dropdown in sidebar."""
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


def render_quick_connect():
    """Render the quick connect section in sidebar."""
    st.sidebar.subheader("⚡ Quick Connect")

    # Cache discovered servers for this session
    if "discovered_servers" not in st.session_state:
        st.session_state.discovered_servers = discover_available_servers()

    servers = st.session_state.discovered_servers
    db_config_manager = st.session_state.db_config_manager
    all_databases = db_config_manager.get_all_databases()

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


def render_manual_connection():
    """Render the manual database connection form in sidebar."""
    st.sidebar.subheader("➕ Add Manually")

    db_config_manager = st.session_state.db_config_manager

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


def render_schema_management():
    """Render the schema management section in sidebar."""
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


def render_other_settings():
    """Render other settings section in sidebar."""
    st.sidebar.subheader("🔧 Other Settings")
    if st.sidebar.button("Reset Chat History"):
        st.session_state.chat_history = []
        st.rerun()


def render_sidebar():
    """Render the complete sidebar with all sections."""
    st.sidebar.title("⚙️ Settings")
    render_database_selector()
    render_quick_connect()
    render_manual_connection()
    render_schema_management()
    render_other_settings()


def render_chat_history():
    """Display the chat history."""
    for entry in st.session_state.chat_history:
        with st.chat_message(entry["role"]):
            st.write(entry["content"])
            if "sql" in entry:
                with st.expander("SQL Query"):
                    st.code(entry["sql"], language="sql")
            if "dataframe" in entry:
                st.dataframe(entry["dataframe"])


def handle_user_query(query, active_schema, current_db_config, sql_generator, query_executor):
    """
    Handle user query: generate SQL and execute it.
    
    Args:
        query: User's natural language query
        active_schema: Database schema string
        current_db_config: Current database configuration
        sql_generator: Function to generate SQL from natural language
        query_executor: Function to execute SQL query
    """
    # Display user message
    with st.chat_message("user"):
        st.write(query)
    st.session_state.chat_history.append({"role": "user", "content": query})

    # Generate SQL
    with st.spinner("Generating SQL..."):
        generated_sql, error = sql_generator(
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
        result = query_executor(
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


def render_main_chat_interface(sql_generator, query_executor):
    """
    Render the main chat interface.
    
    Args:
        sql_generator: Function to generate SQL from natural language
        query_executor: Function to execute SQL query
    """
    st.title("💬 Text-to-SQL Chatbot")

    db_config_manager = st.session_state.db_config_manager

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
    render_chat_history()

    # Chat input
    query = st.chat_input("Ask a question about the database...")

    if query:
        handle_user_query(query, active_schema, current_db_config, sql_generator, query_executor)
