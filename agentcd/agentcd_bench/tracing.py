from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class JsonlTraceLogger:
    path: Path | None

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def event(self, name: str, **fields: Any) -> None:
        if not self.path:
            return
        record = {
            "ts": time.time(),
            "event": name,
            **fields,
        }
        with self._lock:
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, sort_keys=True) + "\n")
