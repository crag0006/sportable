"""Runtime configuration.

Two sources, and only two:

- Environment variables. In Lambda they are baked in by Terraform at apply time
  (``DATABASE_URL``, ``SEARCH_CONFIG``, ``ENVIRONMENT``, ``LOG_LEVEL``,
  ``PUBLIC_BASE_URL``). The function never calls Parameter Store itself: an
  in-VPC Lambda has no route to SSM and the SDK call hangs until the timeout.
  See infra/modules/api/main.tf.
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
DEFAULT_CORRIDOR_M = 400
DEFAULT_STALE_AFTER_DAYS = 365
DEFAULT_EVENTS_WINDOW_DAYS = 28
DEFAULT_EVENTS_MAX_WINDOW_DAYS = 92
DEFAULT_EVENTS_PAGE_SIZE = 50
DEFAULT_TIMEZONE = "Australia/Melbourne"


class SearchConfig(BaseModel):
    """The values the interface renders for AC1.2.4, plus server-side limits."""

    distance_bands_m: list[int] = Field(default_factory=lambda: list(DEFAULT_DISTANCE_BANDS_M))
    default_distance_m: int = DEFAULT_DISTANCE_M
    max_results: int = DEFAULT_MAX_RESULTS
    search_radius_m: int = DEFAULT_SEARCH_RADIUS_M
    corridor_default_m: int = DEFAULT_CORRIDOR_M
    # Applied when the source register carries no threshold for a source.
    default_stale_after_days: int = DEFAULT_STALE_AFTER_DAYS
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
            for name in (
                "default_distance_m",
                "max_results",
                "search_radius_m",
                "corridor_default_m",
                "default_stale_after_days",
            ):
                if name in parsed:
                    setattr(config, name, int(parsed[name]))
            config.source = "terraform"
        except (ValueError, TypeError, AttributeError) as exc:
            log.warning("SEARCH_CONFIG present but unusable, using defaults: %s", exc)
            return cls()
        return config


class EventsConfig(BaseModel):
    """Window and page defaults for /events (contract v0.2 §7)."""

    default_window_days: int = DEFAULT_EVENTS_WINDOW_DAYS
    max_window_days: int = DEFAULT_EVENTS_MAX_WINDOW_DAYS
    page_size: int = DEFAULT_EVENTS_PAGE_SIZE


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str | None = None
    environment: str = "local"
    log_level: str = "INFO"
    search_config: str | None = None
    timezone: str = DEFAULT_TIMEZONE
    # Absolute origin of the SPA, for share links. Differs per environment.
    public_base_url: str | None = None
    events_default_window_days: int = DEFAULT_EVENTS_WINDOW_DAYS
    events_max_window_days: int = DEFAULT_EVENTS_MAX_WINDOW_DAYS
    events_page_size: int = DEFAULT_EVENTS_PAGE_SIZE

    @property
    def search(self) -> SearchConfig:
        return SearchConfig.from_json(self.search_config)

    @property
    def events(self) -> EventsConfig:
        return EventsConfig(
            default_window_days=self.events_default_window_days,
            max_window_days=self.events_max_window_days,
            page_size=self.events_page_size,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
