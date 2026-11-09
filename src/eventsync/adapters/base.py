from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from eventsync.models import RawRecord, Source


class SourceAdapter(Protocol):
    """Anything that can produce raw records for one source.

    The two shipped adapters read JSON files; a live API adapter would
    implement the same single method.
    """

    source: Source

    def fetch(self) -> list[RawRecord]: ...


class JsonFileAdapter:
    source: Source
    id_field: str

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def fetch(self) -> list[RawRecord]:
        with self.path.open(encoding="utf-8") as fh:
            rows = json.load(fh)
        return [RawRecord(source=self.source, source_id=str(r[self.id_field]), payload=r) for r in rows]
