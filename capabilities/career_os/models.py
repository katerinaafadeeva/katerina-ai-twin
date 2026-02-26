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

        # ---------- dual-schema support ----------
        # Old schema: geo_preferences / salary / required_skills / negative_signals / …
        # New schema: seniority_target / hard_skills / domains_preferred / avoid.* / must_have.*

        geo = raw.get("geo_preferences", {})
        salary = raw.get("salary", {})
        avoid = raw.get("avoid", {})
        must_have = raw.get("must_have", {})

        # Seniority: prefer new key "seniority_target", fall back to old "target_seniority"
        target_seniority = tuple(
            raw.get("seniority_target") or raw.get("target_seniority") or []
        )

        # Geo: old schema only (new profile.json omits it → empty)
        geo_cities = tuple(geo.get("cities", []))
        relocation = bool(geo.get("relocation", False))

        # Salary: old schema uses salary.min, new uses must_have.salary_min_rub
        salary_min = int(
            salary.get("min") or must_have.get("salary_min_rub") or 0
        )
        salary_currency = str(salary.get("currency", "RUB"))

        # Skills: prefer "required_skills" (old schema), fall back to "hard_skills"
        required_skills = tuple(
            raw.get("required_skills") or raw.get("hard_skills") or []
        )
        bonus_skills = tuple(raw.get("bonus_skills") or [])

        # Negative signals: old schema top-level, new schema under avoid.keywords_any + avoid.domains
        negative_signals = tuple(
            raw.get("negative_signals")
            or (avoid.get("keywords_any", []) + avoid.get("domains", []))
        )

        # Industries: old schema uses "industries_*", new uses "domains_*"
        industries_preferred = tuple(
            raw.get("industries_preferred") or raw.get("domains_preferred") or []
        )
        industries_excluded = tuple(
            raw.get("industries_excluded") or avoid.get("domains", [])
        )

        # Languages: old schema is a list ["Russian", "English"],
        # new schema is a dict {"ru": "native", "en": "C1"}
        raw_langs = raw.get("languages") or []
        if isinstance(raw_langs, dict):
            languages = tuple(raw_langs.keys())
        else:
            languages = tuple(raw_langs)

        return cls(
            target_roles=tuple(raw.get("target_roles") or []),
            target_seniority=target_seniority,
            work_format=tuple(raw.get("work_format") or []),
            geo_cities=geo_cities,
            relocation=relocation,
            salary_min=salary_min,
            salary_currency=salary_currency,
            required_skills=required_skills,
            bonus_skills=bonus_skills,
            negative_signals=negative_signals,
            industries_preferred=industries_preferred,
            industries_excluded=industries_excluded,
            languages=languages,
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
