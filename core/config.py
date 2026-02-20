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
        )


# Singleton — loaded once at import
config = Config.from_env()
