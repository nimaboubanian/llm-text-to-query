"""Streamlit UI components for the Text-to-Query chatbot."""

import pandas as pd
import streamlit as st

from core.config import APP_TITLE
from core.database_config import (
    DatabaseConfigManager,
    DatabaseType,
    build_connection_url,
    discover_available_servers,
    get_server_databases,
)
from core.schema_helper import (
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

    # Cache discovered servers
    if "discovered_servers" not in st.session_state:
        st.session_state.discovered_servers = discover_available_servers()

    # Build options: (key, label, is_saved, server, db_name)
    db_options = _build_database_options(all_databases, st.session_state.discovered_servers)
    labels = ["-- Select Database --"] + [opt[1] for opt in db_options]

    # Find current selection
    current_index = next(
        (i + 1 for i, opt in enumerate(db_options) if opt[0] == st.session_state.selected_db_key),
        0
    )

    selected_index = st.sidebar.selectbox(
        "Choose Database", range(len(labels)),
        format_func=lambda i: labels[i],
        index=current_index,
        key="db_selector",
    )

    # Handle selection
    if selected_index == 0:
        st.sidebar.info("Please select a database to connect.")
    else:
        _handle_database_selection(db_options[selected_index - 1], db_config_manager)

    # Scan button
    if st.sidebar.button("🔄 Scan for Servers", key="scan_servers"):
        _refresh_discovered_servers()
        st.rerun()

    st.sidebar.caption("💾 Saved  |  🔍 Discovered")


def _build_database_options(all_databases, servers):
    """Build combined list of saved and discovered databases."""
    options = [
        (key, f"💾 {cfg.name} ({cfg.db_type.value})", True, None, None)
        for key, cfg in all_databases.items()
    ]

    saved_urls = {c.url for c in all_databases.values()}

    for server in servers:
        cache_key = f"dbs_{server.host}_{server.port}"
        if cache_key not in st.session_state:
            st.session_state[cache_key] = get_server_databases(server)

        for db_name in st.session_state[cache_key]:
            url = build_connection_url(server, db_name)
            if url not in saved_urls:
                options.append((None, f"🔍 {db_name} ({server.name})", False, server, db_name))

    return options


def _handle_database_selection(option, db_config_manager):
    """Handle database selection - switch or show connect button."""
    key, _, is_saved, server, db_name = option

    if is_saved:
        if key != st.session_state.selected_db_key:
            st.session_state.selected_db_key = key
            st.session_state.current_engine = None
            st.session_state.current_schema = None
            st.session_state.use_manual_schema = False
            st.rerun()
    else:
        if st.sidebar.button("🔗 Connect", key="connect_discovered"):
            url = build_connection_url(server, db_name)
            config_key = db_config_manager.add_database(
                db_name, server.db_type, url
            )
            st.session_state.selected_db_key = config_key
            st.session_state.current_engine = None
            st.session_state.current_schema = None
            st.rerun()


def _refresh_discovered_servers():
    """Clear cached data and rediscover servers."""
    keys_to_clear = [k for k in st.session_state if k.startswith("dbs_")]
    for k in keys_to_clear:
        del st.session_state[k]
    st.session_state.discovered_servers = discover_available_servers()


def render_manual_connection():
    """Render the manual database connection form in sidebar."""
    st.sidebar.subheader("➕ Add Manually")

    with st.sidebar.expander("Custom Database Connection"):
        name = st.text_input("Database Name", key="custom_db_name")
        db_type = st.selectbox(
            "Database Type",
            options=[t.value for t in DatabaseType],
            key="custom_db_type",
        )
        url = st.text_input(
            "Connection URL",
            placeholder="postgresql://user:pass@host:port/dbname",
            key="custom_db_url",
        )

        col1, col2 = st.columns(2)
        db_type_enum = DatabaseType[db_type.upper().replace(" ", "")]

        with col1:
            if st.button("🧪 Test", key="test_conn") and url:
                ok, err = validate_database_connection(url, db_type_enum)
                st.success("✅ OK") if ok else st.error(f"❌ {err}")

        with col2:
            if st.button("➕ Add", key="add_db") and name and url:
                ok, err = validate_database_connection(url, db_type_enum)
                if ok:
                    key = st.session_state.db_config_manager.add_database(name, db_type_enum, url)
                    st.session_state.selected_db_key = key
                    st.session_state.current_engine = None
                    st.session_state.current_schema = None
                    st.rerun()
                else:
                    st.error(f"❌ {err}")


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
    if st.sidebar.button("Reset Saved Databases"):
        st.session_state.db_config_manager.clear_all_databases()
        st.session_state.selected_db_key = None
        st.session_state.current_engine = None
        st.session_state.current_schema = None
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
