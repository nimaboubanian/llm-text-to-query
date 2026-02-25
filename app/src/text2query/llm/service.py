import json
import re
from typing import Generator, Callable

import requests

from text2query.core.config import (
    OLLAMA_URL, DEFAULT_MODEL,
    LLM_TEMPERATURE, LLM_MAX_TOKENS,
)


def abort_ollama_generation(model: str | None = None) -> bool:
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": model or DEFAULT_MODEL, "keep_alive": 0},
            timeout=5,
        )
        return resp.status_code == 200
    except requests.exceptions.RequestException:
        return False


def get_sql_from_llm_streaming(
    user_query: str,
    schema_str: str,
    db_type: str = "postgresql",
    model: str | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> Generator[dict, None, None]:
    """Stream SQL generation. Yields token/done/stopped/error dicts."""
    selected_model = model or DEFAULT_MODEL
    prompt = _build_prompt(user_query, schema_str)
    
    full_response = ""
    stopped = False
    session = None
    response = None
    
    try:
        session = requests.Session()
        session.headers.update({"Connection": "close"})
        
        response = session.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": selected_model,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "temperature": LLM_TEMPERATURE,
                    "num_predict": LLM_MAX_TOKENS,
                },
            },
            timeout=120,
            stream=True,
        )
        
        if response.status_code == 404:
            yield {"type": "error", "message": f"Model '{selected_model}' not found."}
            return
        
        if response.status_code != 200:
            yield {"type": "error", "message": f"LLM API error: {response.status_code}"}
            return
        
        for line in response.iter_lines():
            # Check stop request
            if stop_check and stop_check():
                stopped = True
                response.close()
                abort_ollama_generation(selected_model)
                yield {"type": "stopped", "partial_response": full_response}
                return
            
            if not line:
                continue
                
            try:
                data = json.loads(line)
                token = data.get("response", "")
                if token:
                    full_response += token
                    yield {"type": "token", "content": token}
                
                if data.get("done"):
                    yield {
                        "type": "done",
                        "full_response": full_response,
                        "sql": _clean_sql_response(full_response),
                        "eval_count": data.get("eval_count", 0),
                        "eval_duration": data.get("eval_duration", 0),
                        "total_duration": data.get("total_duration", 0),
                        "prompt_eval_count": data.get("prompt_eval_count", 0),
                    }
                    return
            except json.JSONDecodeError:
                continue
        
        # Stream ended without "done" - return what we have
        yield {
            "type": "done",
            "full_response": full_response,
            "sql": _clean_sql_response(full_response),
            "eval_count": 0,
            "eval_duration": 0,
            "total_duration": 0,
            "prompt_eval_count": 0,
        }
        
    except requests.exceptions.Timeout:
        yield {"type": "error", "message": "Request timed out. Model might be loading."}
    except requests.exceptions.RequestException as e:
        if not stopped:
            yield {"type": "error", "message": f"Connection failed: {e}"}
    finally:
        if response:
            response.close()
        if session:
            session.close()


def _build_prompt(user_query: str, schema_str: str) -> str:
    from text2query.llm.prompts import DEFAULT_SQL_GENERATION_TEMPLATE
    return DEFAULT_SQL_GENERATION_TEMPLATE.format(
        schema=schema_str,
        query=user_query,
    )


def _clean_sql_response(response: str) -> str | None:
    if not response:
        return None

    match = re.search(r"```(?:sql)?\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()

    match = re.search(r"(SELECT|INSERT|UPDATE|DELETE|WITH)\s+.*?;", response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(0).strip()

    return None
