"""Link extractor for Telegram forwarded messages.

Extracts URLs from text, fetches HH.ru vacancy details via API,
or fetches page text for other vacancy-related URLs.
"""

import logging
import re
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# URL pattern
_URL_RE = re.compile(r'https?://[^\s<>"\']+')

# HH vacancy pattern
_HH_VACANCY_RE = re.compile(r'hh\.ru/vacancy/(\d+)')

# Keywords near links that suggest "full description"
_LINK_KEYWORDS = ['описание', 'подробнее', 'подробности', 'откликнуться', 'вакансия', 'детали']


async def extract_links_and_content(text: str) -> dict:
    """Extract URLs from text, fetch relevant ones, return enriched content.

    Returns:
        {
            "hh_vacancy_id": "12345" | None,
            "extracted_text": "full description..." | None,
            "extracted_url": "https://..." | None,
            "original_text": text,
        }
    """
    result = {
        "hh_vacancy_id": None,
        "extracted_text": None,
        "extracted_url": None,
        "original_text": text,
    }

    urls = _URL_RE.findall(text)
    if not urls:
        return result

    # 1. Check for HH vacancy URL
    for url in urls:
        m = _HH_VACANCY_RE.search(url)
        if m:
            result["hh_vacancy_id"] = m.group(1)
            try:
                desc = await _fetch_hh_vacancy(m.group(1))
                if desc:
                    result["extracted_text"] = desc
                    result["extracted_url"] = url
            except Exception:
                logger.warning("Failed to fetch HH vacancy %s", m.group(1))
            return result

    # 2. Check for other URLs with relevant keywords nearby
    for url in urls:
        url_pos = text.find(url)
        context = text[max(0, url_pos - 100):url_pos + len(url) + 100].lower()
        if any(kw in context for kw in _LINK_KEYWORDS):
            try:
                content = await _fetch_page_text(url)
                if content and len(content) > 100:
                    result["extracted_text"] = content[:5000]
                    result["extracted_url"] = url
                    return result
            except Exception:
                continue

    return result


async def _fetch_hh_vacancy(vacancy_id: str) -> Optional[str]:
    """Fetch vacancy description from HH API."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.hh.ru/vacancies/{vacancy_id}",
                headers={"User-Agent": "CareerBot/1.0"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    parts = []
                    if data.get("name"):
                        parts.append(f"Позиция: {data['name']}")
                    if data.get("employer", {}).get("name"):
                        parts.append(f"Компания: {data['employer']['name']}")
                    if data.get("area", {}).get("name"):
                        parts.append(f"Город: {data['area']['name']}")
                    if data.get("description"):
                        desc = re.sub(r'<[^>]+>', ' ', data['description'])
                        desc = re.sub(r'\s+', ' ', desc).strip()
                        parts.append(desc)
                    if data.get("salary"):
                        s = data["salary"]
                        salary = f"ЗП: {s.get('from', '?')}-{s.get('to', '?')} {s.get('currency', '')}"
                        parts.append(salary)
                    return "\n".join(parts) if parts else None
    except Exception:
        logger.warning("HH API fetch failed for vacancy %s", vacancy_id)
    return None


async def _fetch_page_text(url: str) -> Optional[str]:
    """Fetch and extract text from a web page."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
                    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                    text = re.sub(r'<[^>]+>', ' ', text)
                    text = re.sub(r'\s+', ' ', text).strip()
                    return text if len(text) > 100 else None
    except Exception:
        logger.warning("Page fetch failed for url %s", url)
    return None
