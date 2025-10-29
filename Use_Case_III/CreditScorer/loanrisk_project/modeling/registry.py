# loanrisk_project/modeling/registry.py
from __future__ import annotations
from pathlib import Path

class ModelRegistry:
    """Minimal local registry to find the latest model run."""
    def __init__(self, artifacts_dir: str | Path) -> None:
        self.dir = Path(artifacts_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    def latest_run(self) -> Path | None:
        runs = [p for p in self.dir.glob("model_*") if p.is_dir()]
        return max(runs, default=None, key=lambda p: p.stat().st_mtime)

    def path(self, *parts: str) -> Path:
        base = self.latest_run()
        if not base:
            raise FileNotFoundError("No trained model found in artifacts dir.")
        return base.joinpath(*parts)
