import streamlit as st
import requests
import pandas as pd
import os
import time
from sqlalchemy import create_engine, text
from schema_helper import get_database_schema_string

# Environment Variables
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DB_URL = os.getenv("DB_URL")


def wait_for_services(max_retries=10, delay=2):
    """Wait for Ollama and DB to be ready."""
    for i in range(max_retries):
        try:
            requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
            engine = create_engine(DB_URL)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("✅ All services are ready!")
            return True
        except Exception:
            print(f"⏳ Waiting for services... ({i+1}/{max_retries})")
            time.sleep(delay)
    return False


def check_llm():
    """Check if Ollama LLM is online and list models."""
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            models = [m['name'] for m in response.json().get('models', [])]
            print(f"✅ LLM Service Online. Models: {models}")
            return True
        else:
            print("❌ LLM Service Error")
            return False
    except Exception as e:
        print(f"❌ Could not connect to LLM: {e}")
        return False


def check_db(engine):
    """Check database connectivity."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            print("✅ Database Connection Successful")
            return True
    except Exception as e:
        print(f"❌ Could not connect to Database: {e}")
        return False


def get_sql_from_llm(user_query, schema_str):
    """Sends the prompt to Ollama and returns the generated SQL."""
    prompt = (
        f"You are a PostgreSQL SQL query generator. "
        f"Given the following database schema:\n{schema_str}\n\n"
        f"Generate a SQL query to answer: {user_query}\n\n"
        f"Rules:\n"
        f"- Return ONLY the SQL query, nothing else\n"
        f"- No explanations, no comments, no markdown\n"
        f"- Only use tables and columns from the schema above\n"
        f"- Use PostgreSQL syntax"
    )
    
    payload = {
        "model": "llama3.2:3b",
        "prompt": prompt,
        "stream": False
    }
    
    try:
        response = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120)
        
        if response.status_code == 404:
            return None, "Model 'llama3.2:3b' not found. Please run: docker exec thesis_llm ollama pull llama3.2:3b"
        
        if response.status_code != 200:
            return None, f"LLM API error: {response.status_code} - {response.text}"
        
        response_json = response.json()
        sql_query = response_json.get('response', '').strip()
        
        if not sql_query:
            return None, "LLM returned an empty response"
        
        # Clean SQL query - extract only the first SQL statement
        sql_query = clean_sql_response(sql_query)
        
        if not sql_query:
            return None, "Could not extract a valid SQL query from LLM response"
        
        return sql_query, None
        
    except requests.exceptions.Timeout:
        return None, "LLM request timed out. The model might be loading, please try again."
    except requests.exceptions.RequestException as e:
        return None, f"Failed to connect to LLM: {e}"


def clean_sql_response(response):
    """Extract clean SQL from LLM response that may contain markdown or explanations."""
    import re
    
    # Remove markdown code blocks
    # Match ```sql ... ``` or ``` ... ```
    code_block_pattern = r'```(?:sql)?\s*(.*?)```'
    matches = re.findall(code_block_pattern, response, re.DOTALL | re.IGNORECASE)
    if matches:
        # Take the first code block
        return matches[0].strip()
    
    # If no code blocks, try to extract SELECT/INSERT/UPDATE/DELETE statement
    # Find the first SQL statement
    sql_pattern = r'(SELECT|INSERT|UPDATE|DELETE|WITH)\s+.*?;'
    match = re.search(sql_pattern, response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0).strip()
    
    # If no semicolon, try without it
    sql_pattern_no_semi = r'(SELECT|INSERT|UPDATE|DELETE|WITH)\s+[^;]*'
    match = re.search(sql_pattern_no_semi, response, re.DOTALL | re.IGNORECASE)
    if match:
        sql = match.group(0).strip()
        # Stop at common non-SQL patterns
        for stop_word in ['\n\nOR ', '\n\nNote:', '\n\nThis ', '\n\nIf ', '\n\n--']:
            if stop_word in sql:
                sql = sql.split(stop_word)[0].strip()
        return sql
    
    # Last resort: return the first line if it looks like SQL
    first_line = response.split('\n')[0].strip()
    if first_line.upper().startswith(('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'WITH')):
        return first_line
    
    return None


def execute_sql_query(engine, sql_query):
    """Executes the SQL against Postgres and returns a DataFrame."""
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql_query))
            rows = result.fetchall()
            columns = result.keys()
            df = pd.DataFrame(rows, columns=columns)
            return df
    except Exception as e:
        return str(e)


def main():
    """Main Streamlit application."""
    # Page Config (must be first Streamlit command)
    st.set_page_config(page_title="Text-to-SQL Chatbot")
    
    # Initialize database engine
    if not DB_URL:
        st.error("❌ DB_URL environment variable is not set!")
        return
    
    engine = create_engine(DB_URL)
    
    # Get schema
    try:
        schema_string = get_database_schema_string(engine)
    except Exception as e:
        st.error(f"❌ Could not fetch database schema: {e}")
        return
    
    # --- Sidebar ---
    st.sidebar.title("Settings")
    if st.sidebar.button("Reset Chat"):
        st.session_state.chat_history = []
        st.rerun()
    
    # Show schema in sidebar
    with st.sidebar.expander("Database Schema"):
        st.code(schema_string, language="sql")
    
    # --- Main Chat Interface ---
    st.title("Text-to-SQL Chatbot")
    
    # Initialize chat history
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
    
    # Display chat history
    for entry in st.session_state.chat_history:
        with st.chat_message(entry['role']):
            st.write(entry['content'])
            if 'sql' in entry:
                with st.expander("SQL Query"):
                    st.code(entry['sql'], language="sql")
            if 'dataframe' in entry:
                st.dataframe(entry['dataframe'])
    
    # Chat input
    query = st.chat_input("Ask a question about the database...")
    
    if query:
        # Display user message
        with st.chat_message("user"):
            st.write(query)
        st.session_state.chat_history.append({"role": "user", "content": query})
        
        # Generate SQL
        with st.spinner("Generating SQL..."):
            generated_sql, error = get_sql_from_llm(query, schema_string)
        
        if error:
            # Handle LLM error
            with st.chat_message("assistant"):
                st.error(f"❌ {error}")
            st.session_state.chat_history.append({
                "role": "assistant",
                "content": f"Error: {error}"
            })
        else:
            # Execute query
            result = execute_sql_query(engine, generated_sql)
            
            # Display assistant response
            with st.chat_message("assistant"):
                with st.expander("Generated SQL Query", expanded=True):
                    st.code(generated_sql, language="sql")
                
                if isinstance(result, pd.DataFrame):
                    st.write("Here is the result of your query:")
                    st.dataframe(result)
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": "Here is the result of your query:",
                        "sql": generated_sql,
                        "dataframe": result
                    })
                else:
                    st.error(f"Error executing SQL: {result}")
                    st.session_state.chat_history.append({
                        "role": "assistant",
                        "content": f"Error executing SQL: {result}",
                        "sql": generated_sql
                    })


if __name__ == "__main__":
    main()
