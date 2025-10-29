from pathlib import Path
import yaml
from typing import Any

class Config:
    """YAML config wrapper."""

    def __init__(self, path: str | Path = "config.yaml") -> None:
        self._path = Path(path)
        with open(self._path, "r") as f:
            self._cfg: dict[str, Any] = yaml.safe_load(f)

    def get(self, *keys: str, default: Any = None) -> Any:
        node = self._cfg
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    @property
    def raw_dir(self) -> Path:
        return Path(self.get("paths", "raw_dir"))

    @property
    def processed_dir(self) -> Path:
        return Path(self.get("paths", "processed_dir"))

    @property
    def artifacts_dir(self) -> Path:
        return Path(self.get("paths", "artifacts_dir"))
