"""Main application entry point for LLM Text-to-Query chatbot."""

import streamlit as st

try:
    from .config import APP_TITLE
    from .llm_service import get_sql_from_llm
    from .query_executor import execute_sql_query
    from .ui import init_session_state, render_sidebar, render_main_chat_interface
except ImportError:
    from config import APP_TITLE
    from llm_service import get_sql_from_llm
    from query_executor import execute_sql_query
    from ui import init_session_state, render_sidebar, render_main_chat_interface


def main():
    """Main Streamlit application entry point."""
    # Page Config (must be first Streamlit command)
    st.set_page_config(page_title=APP_TITLE, layout="wide")

    # Initialize session state
    init_session_state()

    # Render sidebar with all settings
    render_sidebar()

    # Render main chat interface with business logic functions
    render_main_chat_interface(get_sql_from_llm, execute_sql_query)


if __name__ == "__main__":
    main()

