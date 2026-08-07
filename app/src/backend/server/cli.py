import json
import sys
import urllib.error
import urllib.request

from backend.core.config import LLM_TIMEOUT, SERVER_PORT

SERVER_URL = f"http://127.0.0.1:{SERVER_PORT}/query"

# Wait a little longer than the server's own generation timeout so the client
# doesn't give up on a slow query the server would still answer.
CLIENT_TIMEOUT = LLM_TIMEOUT + 30


def format_table(columns: list[str], rows: list[list]) -> str:
    if not rows:
        return "(empty result set)"

    widths = [
        max(len(str(col)), max((len(str(row[i])) for row in rows), default=0))
        for i, col in enumerate(columns)
    ]
    lines = ["  ".join(str(c).ljust(w) for c, w in zip(columns, widths))]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(str(v).ljust(w) for v, w in zip(row, widths)))
    return "\n".join(lines)


def format_result(payload: dict) -> str:
    return "\n".join([
        payload["sql"],
        "",
        format_table(payload["columns"], payload["rows"]),
        "",
        f"{payload['row_count']} row(s)",
    ])


def query_server(question: str, timeout: int = CLIENT_TIMEOUT) -> dict:
    """POST a question to the app server and return the parsed JSON response."""
    body = json.dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(
        SERVER_URL, data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except json.JSONDecodeError:
            return {"error": f"Server returned HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"error": f"Could not reach text2query server: {e.reason}"}


def main():
    if len(sys.argv) != 2:
        print("Usage: text2query '<question>'", file=sys.stderr)
        sys.exit(1)

    payload = query_server(sys.argv[1])

    if payload.get("error"):
        print(f"Error: {payload['error']}", file=sys.stderr)
        sys.exit(1)

    print(format_result(payload))


if __name__ == "__main__":
    main()
