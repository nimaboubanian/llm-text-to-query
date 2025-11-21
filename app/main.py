import requests
import os
import time
from sqlalchemy import create_engine, text

# Environment Variables
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
DB_URL = os.getenv("DB_URL")

def wait_for_services():
    """Wait for Ollama and DB to be ready."""
    print("Waiting for services...")
    time.sleep(5) 

def check_llm():
    try:
        print(f"Checking LLM at {OLLAMA_URL}...")
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        if response.status_code == 200:
            print("✅ LLM Service (Ollama) is Online")
            models = [m['name'] for m in response.json()['models']]

        else:
            print("❌ LLM Service Error ❌")
    except Exception as e:
        print(f"❌ Could not connect to LLM: {e} ❌")

def check_db():
    try:
        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1")).scalar()
            print(f"✅ Database Connection Successful (Result: {result})")
    except Exception as e:
        print(f"❌ Could not connect to Database: {e} ❌")

if __name__ == "__main__":
    wait_for_services()
    check_llm()
    check_db()
