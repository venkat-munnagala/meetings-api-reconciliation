"""Runtime settings. Every tunable the pipeline uses lives here and is echoed by /api/stats."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    data_dir: Path = REPO_ROOT / "data"
    local_tz: str = "America/New_York"
    internal_domain: str = "firma.com"
    tight_window_min: int = 10
    dedupe_window_min: int = 60
    dedupe_jaccard: float = 0.5
    title_overlap: float = 0.3
    auto_merge_levels: frozenset[int] = field(default_factory=lambda: frozenset({1}))
    normalizer_version: str = "1"
    host: str = "127.0.0.1"
    port: int = 8000

    def as_dict(self) -> dict:
        return {
            "data_dir": str(self.data_dir),
            "local_tz": self.local_tz,
            "internal_domain": self.internal_domain,
            "tight_window_min": self.tight_window_min,
            "dedupe_window_min": self.dedupe_window_min,
            "dedupe_jaccard": self.dedupe_jaccard,
            "title_overlap": self.title_overlap,
            "auto_merge_levels": sorted(self.auto_merge_levels),
            "normalizer_version": self.normalizer_version,
        }


DEFAULT = Settings()
