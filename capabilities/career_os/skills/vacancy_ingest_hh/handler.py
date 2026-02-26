"""Orchestration for HH vacancy ingestion.

Connects HH API client → pre-filter → dedup → store → events.
No LLM calls — all processing is deterministic.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from capabilities.career_os.models import Profile
from capabilities.career_os.skills.vacancy_ingest_hh.filters import should_score_advanced
from capabilities.career_os.skills.vacancy_ingest_hh.prefilter import should_score
from capabilities.career_os.skills.vacancy_ingest_hh.store import (
    compute_canonical_key,
    is_canonical_key_ingested,
    is_hh_vacancy_ingested,
    save_hh_vacancy,
)
from core.config import config
from core.db import get_conn
from core.events import emit

logger = logging.getLogger(__name__)


def load_search_queries(path: str) -> List[Dict[str, str]]:
    """Load HH search queries from JSON file.

    Expects a JSON array of dicts, each with at least a "text" key.
    Returns empty list if file not found (logged as warning).
    """
    p = Path(path)
    if not p.exists():
        logger.warning("HH searches file not found: %s — create from example", path)
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        logger.error("HH searches file is invalid JSON: %s", exc)
        return []

    if not isinstance(data, list):
        logger.error(
            "HH searches file must contain a JSON array, got %s", type(data).__name__
        )
        return []

    queries = [q for q in data if isinstance(q, dict) and q.get("text")]
    if not queries:
        logger.warning("HH searches file contains no valid queries with 'text' field")
    return queries


def _strip_html(text: str) -> str:
    """Remove basic HTML tags from HH API snippet fields."""
    return re.sub(r"<[^>]+>", "", text).strip()


def normalize_vacancy(item: Dict[str, Any]) -> Dict[str, Any]:
    """Extract relevant fields from HH API vacancy item into a flat dict.

    Builds raw_text from name + employer + snippet for LLM scoring.
    Returns dict with: hh_vacancy_id, raw_text, source_url,
    salary_min, salary_currency, has_salary.
    """
    name = item.get("name", "")

    employer_name = ""
    employer = item.get("employer")
    if isinstance(employer, dict):
        employer_name = employer.get("name", "")

    snippet = item.get("snippet") or {}
    requirement = _strip_html(snippet.get("requirement") or "")
    responsibility = _strip_html(snippet.get("responsibility") or "")

    # Salary
    salary_str = ""
    salary_min: Optional[int] = None
    salary_currency: str = ""
    has_salary: bool = False
    salary = item.get("salary")
    if isinstance(salary, dict) and salary:
        has_salary = True
        salary_currency = salary.get("currency", "") or ""
        raw_from = salary.get("from")
        raw_to = salary.get("to")
        if raw_from is not None:
            salary_min = int(raw_from)
        parts = []
        if raw_from:
            parts.append(f"от {raw_from}")
        if raw_to:
            parts.append(f"до {raw_to}")
        if parts:
            salary_str = " ".join(parts) + (f" {salary_currency}" if salary_currency else "")

    # Area
    area_name = ""
    area = item.get("area")
    if isinstance(area, dict):
        area_name = area.get("name", "")

    # Schedule
    schedule_name = ""
    schedule = item.get("schedule")
    if isinstance(schedule, dict):
        schedule_name = schedule.get("name", "")

    raw_parts = [f"Позиция: {name}"]
    if employer_name:
        raw_parts.append(f"Компания: {employer_name}")
    if area_name:
        raw_parts.append(f"Город: {area_name}")
    if schedule_name:
        raw_parts.append(f"Формат: {schedule_name}")
    if salary_str:
        raw_parts.append(f"ЗП: {salary_str}")
    if requirement:
        raw_parts.append(f"\nТребования:\n{requirement}")
    if responsibility:
        raw_parts.append(f"\nОбязанности:\n{responsibility}")

    raw_text = "\n".join(raw_parts)
    hh_id = str(item.get("id", ""))
    source_url = item.get("alternate_url", "")

    return {
        "hh_vacancy_id": hh_id,
        "raw_text": raw_text,
        "source_url": source_url,
        "salary_min": salary_min,
        "salary_currency": salary_currency,
        "has_salary": has_salary,
    }


def ingest_hh_vacancies(
    vacancies: List[Dict[str, Any]],
    profile: Profile,
) -> Dict[str, int]:
    """Process a batch of HH API vacancy items.

    Flow per vacancy:
    1. Skip if no hh_vacancy_id
    2. Dedup by hh_vacancy_id (fast path — HH index)
    3. Pre-filter by negative_signals/industries_excluded (no LLM)
    4. Dedup by canonical_key (cross-source: catches TG↔HH duplicates)
    5. Save to job_raw, emit vacancy.ingested

    Pre-filtered vacancies are NOT saved to job_raw (prevents spurious LLM scoring).

    Args:
        vacancies: Raw vacancy dicts from HH API.
        profile: Operator profile with filter lists.

    Returns:
        Dict with counts: total, new, duplicate, filtered.
    """
    counts: Dict[str, int] = {"total": 0, "new": 0, "duplicate": 0, "filtered": 0}

    for item in vacancies:
        counts["total"] += 1
        normalized = normalize_vacancy(item)
        hh_id = normalized["hh_vacancy_id"]

        if not hh_id:
            logger.warning("HH vacancy missing id — skipping")
            continue

        # Dedup level 1: fast HH ID check
        with get_conn() as conn:
            if is_hh_vacancy_ingested(conn, hh_id):
                counts["duplicate"] += 1
                continue

        # Pre-filter level 1: profile-based negative signals / excluded industries
        passes, reason = should_score(normalized["raw_text"], profile)
        if not passes:
            logger.debug("HH vacancy %s pre-filtered: %s", hh_id, reason)
            counts["filtered"] += 1
            continue

        # Pre-filter level 2: identity-level advanced filters from hh_filters.json
        passes, reason = should_score_advanced(
            vacancy_text=normalized["raw_text"],
            salary_min=normalized["salary_min"],
            salary_currency=normalized["salary_currency"],
            has_salary=normalized["has_salary"],
            filters_path=config.hh_filters_path,
        )
        if not passes:
            logger.debug("HH vacancy %s advanced-filtered: %s", hh_id, reason)
            counts["filtered"] += 1
            continue

        # Dedup level 2: canonical_key (cross-source TG↔HH)
        key = compute_canonical_key(normalized["raw_text"])
        with get_conn() as conn:
            if is_canonical_key_ingested(conn, key):
                logger.debug(
                    "HH vacancy %s canonical_key duplicate (already in job_raw from other source)",
                    hh_id,
                )
                counts["duplicate"] += 1
                continue

        # Save to job_raw
        with get_conn() as conn:
            job_raw_id, is_new = save_hh_vacancy(
                conn,
                hh_id,
                normalized["raw_text"],
                normalized["source_url"],
            )
            conn.commit()

        if is_new:
            counts["new"] += 1
            emit(
                "vacancy.ingested",
                {
                    "job_raw_id": job_raw_id,
                    "source": "hh",
                    "hh_vacancy_id": hh_id,
                },
                actor="hh_ingest",
            )
        else:
            counts["duplicate"] += 1

    return counts
