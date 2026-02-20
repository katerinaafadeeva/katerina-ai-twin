"""Profile model for career_os capability.

Loaded from identity/profile.json (or fallback to identity/profile.example.json).
Frozen dataclass — treat as value object. Use content_hash() for cache invalidation.
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)

_FALLBACK_PATH = "identity/profile.example.json"


@dataclass(frozen=True)
class Profile:
    """Frozen representation of the job-seeker's targeting profile.

    All fields correspond directly to the JSON profile schema.
    Nested structures (geo_preferences, salary) are flattened at load time.
    """

    target_roles: tuple
    target_seniority: tuple
    work_format: tuple
    geo_cities: tuple
    relocation: bool
    salary_min: int
    salary_currency: str
    required_skills: tuple
    bonus_skills: tuple
    negative_signals: tuple
    industries_preferred: tuple
    industries_excluded: tuple
    languages: tuple

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_file(cls, path: str) -> "Profile":
        """Load a Profile from a JSON file.

        If the file at *path* does not exist, falls back to
        ``identity/profile.example.json`` and logs a warning.

        Args:
            path: Path to the profile JSON file
                  (typically ``config.profile_path`` → ``identity/profile.json``).

        Returns:
            Populated Profile instance.

        Raises:
            FileNotFoundError: If neither *path* nor the fallback exist.
            KeyError / ValueError: If the JSON is missing required fields.
        """
        if not os.path.exists(path):
            logger.warning(
                "Profile not found at %r — falling back to %r. "
                "Copy identity/profile.example.json to identity/profile.json "
                "and fill in real values.",
                path,
                _FALLBACK_PATH,
            )
            path = _FALLBACK_PATH

        with open(path, "r", encoding="utf-8") as fh:
            raw: dict = json.load(fh)

        geo = raw.get("geo_preferences", {})
        salary = raw.get("salary", {})

        return cls(
            target_roles=tuple(raw["target_roles"]),
            target_seniority=tuple(raw["target_seniority"]),
            work_format=tuple(raw["work_format"]),
            geo_cities=tuple(geo.get("cities", [])),
            relocation=bool(geo.get("relocation", False)),
            salary_min=int(salary.get("min", 0)),
            salary_currency=str(salary.get("currency", "RUB")),
            required_skills=tuple(raw["required_skills"]),
            bonus_skills=tuple(raw["bonus_skills"]),
            negative_signals=tuple(raw["negative_signals"]),
            industries_preferred=tuple(raw["industries_preferred"]),
            industries_excluded=tuple(raw["industries_excluded"]),
            languages=tuple(raw["languages"]),
        )

    # ------------------------------------------------------------------
    # Cache key
    # ------------------------------------------------------------------

    def content_hash(self) -> str:
        """Return a short SHA-256 hash of this profile for cache-key use.

        The serialisation is deterministic (sorted keys, stable list order).
        Only the first 16 hex characters are returned — sufficient for a
        cache-invalidation signal, not meant as a cryptographic identifier.

        Returns:
            16-character hex string (64 bits of SHA-256).
        """
        payload = {
            "target_roles": list(self.target_roles),
            "target_seniority": list(self.target_seniority),
            "work_format": list(self.work_format),
            "geo_cities": list(self.geo_cities),
            "relocation": self.relocation,
            "salary_min": self.salary_min,
            "salary_currency": self.salary_currency,
            "required_skills": list(self.required_skills),
            "bonus_skills": list(self.bonus_skills),
            "negative_signals": list(self.negative_signals),
            "industries_preferred": list(self.industries_preferred),
            "industries_excluded": list(self.industries_excluded),
            "languages": list(self.languages),
        }
        serialised = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialised.encode()).hexdigest()[:16]
