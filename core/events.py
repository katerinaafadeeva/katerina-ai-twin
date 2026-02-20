import json
import logging
from typing import Optional

from core.db import get_conn

logger = logging.getLogger(__name__)


def emit(
    event_name: str,
    payload: dict,
    actor: str = "system",
    correlation_id: Optional[str] = None,
) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO events (event_name, payload_json, actor, correlation_id) VALUES (?, ?, ?, ?)",
            (event_name, json.dumps(payload, ensure_ascii=False), actor, correlation_id),
        )
