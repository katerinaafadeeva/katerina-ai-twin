import logging

from aiogram.types import Message

from core.config import config

logger = logging.getLogger(__name__)


def is_authorized(message: Message) -> bool:
    """Check if Telegram user is in whitelist. Empty list = dev mode (allow all)."""
    if not config.allowed_telegram_ids:
        logger.warning("ALLOWED_TELEGRAM_IDS is empty — dev mode, all users allowed")
        return True
    return message.from_user is not None and message.from_user.id in config.allowed_telegram_ids
