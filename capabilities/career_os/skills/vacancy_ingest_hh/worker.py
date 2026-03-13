"""Async background worker for HH.ru vacancy ingestion.

Polls HH API on configurable interval. Feeds vacancies into
the existing scoring → policy → approval pipeline.
Starts only when HH_ENABLED=true.
"""

import asyncio
import logging

from capabilities.career_os.models import Profile
from capabilities.career_os.skills.vacancy_ingest_hh.handler import (
    ingest_hh_vacancies,
    load_search_queries,
)
from connectors.hh_api import HHApiClient
from core.config import config
from core.events import emit

logger = logging.getLogger(__name__)


async def hh_ingest_worker() -> None:
    """Background worker: polls HH.ru API and ingests new vacancies.

    Runs in infinite loop. On each cycle:
    1. Load search queries from config path.
    2. For each query: fetch vacancies from HH API (paginated, rate-limited).
    3. Normalize, pre-filter, dedup, save to job_raw, emit events.
    4. Emit hh.search_completed event with cycle totals.
    5. Sleep for hh_poll_interval seconds.

    Exits immediately if HH_ENABLED=false.
    Per-query errors are caught and logged; the loop continues to next query.
    Loop-level errors are caught and logged; worker sleeps and retries.
    """
    if not config.hh_enabled:
        logger.info("HH ingest worker disabled (HH_ENABLED=false) — exiting")
        return

    interval = config.hh_poll_interval
    profile = Profile.from_file(config.profile_path)
    client = HHApiClient(
        user_agent=config.hh_user_agent,
        max_pages=config.hh_max_pages,
    )

    logger.info(
        "HH ingest worker started (interval=%ds, max_pages=%d)",
        interval,
        config.hh_max_pages,
    )

    while True:
        try:
            queries = load_search_queries(config.hh_searches_path)
            if not queries:
                logger.warning(
                    "No HH search queries configured — skipping cycle. "
                    "Create %s from %s.example.json",
                    config.hh_searches_path,
                    config.hh_searches_path,
                )
                await asyncio.sleep(interval)
                continue

            cycle_counts: dict = {"total": 0, "new": 0, "duplicate": 0, "filtered": 0}

            for i, query_params in enumerate(queries):
                query_text = query_params.get("text", "?")
                try:
                    logger.info(
                        "HH search %d/%d: '%s'",
                        i + 1,
                        len(queries),
                        query_text,
                    )
                    items = await client.search_vacancies(query_params)
                    counts = ingest_hh_vacancies(items, profile)

                    for key in cycle_counts:
                        cycle_counts[key] += counts[key]

                    logger.info(
                        "HH search %d/%d done: total=%d new=%d dup=%d filtered=%d archived=%d",
                        i + 1,
                        len(queries),
                        counts["total"],
                        counts["new"],
                        counts["duplicate"],
                        counts["filtered"],
                        counts.get("archived", 0),
                    )
                except Exception:
                    logger.exception(
                        "HH search %d/%d failed for query '%s'",
                        i + 1,
                        len(queries),
                        query_text,
                    )

            emit("hh.search_completed", cycle_counts, actor="hh_ingest")

            logger.info(
                "HH ingest cycle complete: new=%d total=%d",
                cycle_counts["new"],
                cycle_counts["total"],
            )

        except Exception:
            logger.exception("HH ingest worker cycle error")

        await asyncio.sleep(interval)
