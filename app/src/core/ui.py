"""Streamlit UI components for the Text-to-Query chatbot."""

import pandas as pd
import streamlit as st

try:
    from .config import APP_TITLE
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
    from config import APP_TITLE
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
    """Render unified database selection with saved and discovered databases."""
    st.sidebar.subheader("🗄️ Database Connection")

    db_config_manager = st.session_state.db_config_manager
    all_databases = db_config_manager.get_all_databases()

    # Cache discovered servers for this session
    if "discovered_servers" not in st.session_state:
        st.session_state.discovered_servers = discover_available_servers()

    servers = st.session_state.discovered_servers

    # Build combined list: saved databases + discovered (not yet saved)
    db_options = []  # List of (key, label, is_saved, server_info, db_name)

    # Add saved databases first
    for key, config in all_databases.items():
        label = f"💾 {config.name} ({config.db_type.value})"
        db_options.append((key, label, True, None, None))

    # Add discovered databases that aren't already saved
    for server in servers:
        cache_key = f"dbs_{server.host}_{server.port}"
        if cache_key not in st.session_state:
            st.session_state[cache_key] = get_server_databases(server)

        databases = st.session_state[cache_key]
        for db_name in databases:
            connection_url = build_connection_url(server, db_name)
            # Check if this database is already saved
            already_saved = any(c.url == connection_url for c in all_databases.values())
            if not already_saved:
                label = f"🔍 {db_name} ({server.name})"
                db_options.append((None, label, False, server, db_name))

    if db_options:
        # Build display labels with placeholder
        labels = ["-- Select Database --"] + [opt[1] for opt in db_options]

        # Find current selection index (offset by 1 due to placeholder)
        current_index = 0
        if st.session_state.selected_db_key:
            for i, opt in enumerate(db_options):
                if opt[0] == st.session_state.selected_db_key:
                    current_index = i + 1  # +1 for placeholder
                    break

        selected_index = st.sidebar.selectbox(
            "Choose Database",
            range(len(labels)),
            format_func=lambda i: labels[i],
            index=current_index,
            key="db_selector",
        )

        # Handle placeholder selection
        if selected_index == 0:
            st.sidebar.info("Please select a database to connect.")
            if st.sidebar.button("🔄 Scan for Servers", key="scan_servers_placeholder"):
                _refresh_discovered_servers()
                st.rerun()
        else:
            selected_option = db_options[selected_index - 1]  # -1 for placeholder offset
            selected_key, _, is_saved, server_info, db_name = selected_option

            # Handle selection change
            if is_saved:
                # Saved database - just switch to it
                if selected_key != st.session_state.selected_db_key:
                    st.session_state.selected_db_key = selected_key
                    st.session_state.current_engine = None
                    st.session_state.current_schema = None
                    st.session_state.use_manual_schema = False
                    st.rerun()
            else:
                # Discovered database - show connect button
                col1, col2 = st.sidebar.columns(2)
                with col1:
                    if st.button("🔗 Connect", key="connect_discovered"):
                        connection_url = build_connection_url(server_info, db_name)
                        display_name = f"{db_name} ({server_info.name})"
                        config_key = db_config_manager.add_database(
                            display_name, server_info.db_type, connection_url
                        )
                        st.session_state.selected_db_key = config_key
                        st.sidebar.success("✅ Connected!")
                        st.rerun()
                with col2:
                    if st.button("🔄 Refresh", key="refresh_servers"):
                        _refresh_discovered_servers()
                        st.rerun()

            # Refresh button when a saved database is selected
            if is_saved:
                if st.sidebar.button("🔄 Scan for Servers", key="scan_servers"):
                    _refresh_discovered_servers()
                    st.rerun()
    else:
        st.sidebar.info("No databases available. Scan for servers or add manually.")
        if st.sidebar.button("🔄 Scan for Servers", key="scan_servers_empty"):
            _refresh_discovered_servers()
            st.rerun()

    # Show legend
    st.sidebar.caption("💾 Saved  |  🔍 Discovered")


def _refresh_discovered_servers():
    """Clear cached data and rediscover servers."""
    keys_to_clear = [k for k in st.session_state if k.startswith("dbs_")]
    for k in keys_to_clear:
        del st.session_state[k]
    st.session_state.discovered_servers = discover_available_servers()


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
            placeholder="Table 'users' has columns: id (INTEGER), name (VARCHAR), email (VARCHAR)\nTable 'orders' has columns: id (INTEGER), user_id (INTEGER), total (DECIMAL). FOREIGN KEY (user_id) REFERENCES users(id)",
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
    st.sidebar.divider()
    render_manual_connection()
    st.sidebar.divider()
    render_schema_management()
    st.sidebar.divider()
    render_other_settings()


def apply_custom_styles():
    """Apply custom CSS styles to the app."""
    custom_css = """
        <style>
        /* Hide anchor links on headers */
        .stMarkdown a[href^="#"] {
            display: none !important;
        }
        h1 a, h2 a, h3 a {
            display: none !important;
        }
        /* Fix cursor for selectbox dropdowns */
        .stSelectbox > div > div {
            cursor: pointer !important;
        }
        .stSelectbox input {
            cursor: pointer !important;
        }
        </style>
    """
    st.markdown(custom_css, unsafe_allow_html=True)


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
    apply_custom_styles()
    st.markdown(
        f"<h1 style='text-align: center;'>💬 {APP_TITLE}</h1>",
        unsafe_allow_html=True,
    )

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
