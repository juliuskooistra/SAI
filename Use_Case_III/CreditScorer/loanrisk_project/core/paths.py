from pathlib import Path
from dataclasses import dataclass

@dataclass(frozen=True)
class Paths:
    raw: Path
    processed: Path
    artifacts: Path

    def ensure(self) -> None:
        self.raw.mkdir(parents=True, exist_ok=True)
        self.processed.mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(parents=True, exist_ok=True)
