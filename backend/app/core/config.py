"""Runtime configuration.

Two sources, and only two:

- Environment variables. In Lambda they are baked in by Terraform at apply time
  (``DATABASE_URL``, ``SEARCH_CONFIG``, ``ENVIRONMENT``, ``LOG_LEVEL``). The
  function never calls Parameter Store itself: an in-VPC Lambda has no route to
  SSM and the SDK call hangs until the timeout. See infra/modules/api/main.tf.
- A ``.env`` file next to the working directory, for local development only.
  It is git-ignored.

``SEARCH_CONFIG`` arrives as one JSON blob whose values are all strings, because
Parameter Store has no numeric type. Every field is coerced explicitly rather
than trusted, and a malformed blob degrades to the committed defaults with
``source = "fallback"`` so the degradation is visible rather than silent.
"""

import json
import logging
from functools import lru_cache
from typing import Any, Self

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

DEFAULT_DISTANCE_BANDS_M: tuple[int, ...] = (250, 500, 1000)
DEFAULT_DISTANCE_M = 500
DEFAULT_MAX_RESULTS = 100
DEFAULT_SEARCH_RADIUS_M = 10_000


class SearchConfig(BaseModel):
    """The values the interface renders for AC1.2.4, plus server-side limits."""

    distance_bands_m: list[int] = Field(default_factory=lambda: list(DEFAULT_DISTANCE_BANDS_M))
    default_distance_m: int = DEFAULT_DISTANCE_M
    max_results: int = DEFAULT_MAX_RESULTS
    search_radius_m: int = DEFAULT_SEARCH_RADIUS_M
    source: str = "fallback"

    @classmethod
    def from_json(cls, raw: str | None) -> Self:
        """Parse the Terraform-supplied blob. Never raises."""
        config = cls()
        if not raw:
            return config
        try:
            parsed: dict[str, Any] = json.loads(raw)
            if "distance_bands_m" in parsed:
                bands = str(parsed["distance_bands_m"]).strip("[]")
                config.distance_bands_m = [int(v) for v in bands.split(",") if v.strip()]
            if "default_distance_m" in parsed:
                config.default_distance_m = int(parsed["default_distance_m"])
            if "max_results" in parsed:
                config.max_results = int(parsed["max_results"])
            if "search_radius_m" in parsed:
                config.search_radius_m = int(parsed["search_radius_m"])
            config.source = "terraform"
        except (ValueError, TypeError, AttributeError) as exc:
            log.warning("SEARCH_CONFIG present but unusable, using defaults: %s", exc)
            return cls()
        return config


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str | None = None
    environment: str = "local"
    log_level: str = "INFO"
    search_config: str | None = None

    @property
    def search(self) -> SearchConfig:
        return SearchConfig.from_json(self.search_config)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
