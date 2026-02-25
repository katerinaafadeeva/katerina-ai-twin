import os
from dataclasses import dataclass
from typing import List

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: str
    anthropic_api_key: str
    allowed_telegram_ids: List[int]
    profile_path: str
    log_level: str
    scoring_worker_interval: int  # seconds

    # HH.ru integration
    hh_enabled: bool
    hh_poll_interval: int       # seconds between HH poll cycles
    hh_user_agent: str          # User-Agent for HH API
    hh_max_pages: int           # max search result pages to fetch
    hh_scoring_daily_cap: int   # max LLM scoring calls per day (0 = no cap)
    hh_searches_path: str       # path to search queries JSON

    # Cover letter generation
    cover_letter_daily_cap: int      # max LLM cover letter calls per day (0 = no cap)
    cover_letter_fallback_path: str  # path to fallback template file

    @classmethod
    def from_env(cls) -> "Config":
        ids_raw = os.getenv("ALLOWED_TELEGRAM_IDS", "")
        ids = [int(x.strip()) for x in ids_raw.split(",") if x.strip()]
        return cls(
            bot_token=os.environ["BOT_TOKEN"],
            db_path=os.getenv("DB_PATH", "data/career.db"),
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            allowed_telegram_ids=ids,
            profile_path=os.getenv("PROFILE_PATH", "identity/profile.json"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
            scoring_worker_interval=int(os.getenv("SCORING_WORKER_INTERVAL", "10")),
            # HH
            hh_enabled=os.getenv("HH_ENABLED", "false").lower() in ("true", "1", "yes"),
            hh_poll_interval=int(os.getenv("HH_POLL_INTERVAL", "3600")),
            hh_user_agent=os.getenv("HH_USER_AGENT", "KaterinaAITwin/0.1"),
            hh_max_pages=int(os.getenv("HH_MAX_PAGES", "5")),
            hh_scoring_daily_cap=int(os.getenv("HH_SCORING_DAILY_CAP", "100")),
            hh_searches_path=os.getenv("HH_SEARCHES_PATH", "identity/hh_searches.json"),
            # Cover letter
            cover_letter_daily_cap=int(os.getenv("COVER_LETTER_DAILY_CAP", "50")),
            cover_letter_fallback_path=os.getenv(
                "COVER_LETTER_FALLBACK_PATH", "identity/cover_letter_fallback.txt"
            ),
        )


# Singleton — loaded once at import
config = Config.from_env()
