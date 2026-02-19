import json
from core.db import get_conn


def emit(event_name: str, payload: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO events (event_name, payload_json) VALUES (?, ?)",
            (event_name, json.dumps(payload, ensure_ascii=False)),
        )
