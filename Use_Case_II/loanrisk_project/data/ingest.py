# loanrisk_project/data/ingest.py
from __future__ import annotations
from pathlib import Path
from typing import List
import pandas as pd
import kagglehub  # make sure kagglehub is installed

from loanrisk_project.core.config import Config
from loanrisk_project.core.paths import Paths
from loanrisk_project.utils import write_parquet


class DataIngestor:
    """
    Load raw lending data (Kaggle or local) and persist a unified raw table.
    Prefers Feather for speed/size, falls back to CSV otherwise.
    """

    def __init__(self, cfg: Config, paths: Paths) -> None:
        self.cfg = cfg
        self.paths = paths

    def _load_from_kaggle(self) -> pd.DataFrame:
        dataset = self.cfg.get("data_source", "kagglehub", "dataset")
        if not dataset:
            raise ValueError("Config missing data_source.kagglehub.dataset")

        # download dataset
        dl_path = Path(kagglehub.dataset_download(dataset))
        files: List[Path] = list(dl_path.glob("*"))

        # --- Prefer Feather ---
        feather_files = [f for f in files if f.suffix == ".feather"]
        if feather_files:
            print("Loading Feather file:", feather_files[0])
            df = pd.read_feather(feather_files[0])
            print("Shape after Feather load:", df.shape)
            return df

        # --- Fall back to CSV (skip dict/sample) ---
        csv_files = [
            f for f in files
            if f.suffix == ".csv" and "dict" not in f.name.lower() and "sample" not in f.name.lower()
        ]
        if csv_files:
            print("CSV files found:", csv_files[:5])
            dfs = [pd.read_csv(f, low_memory=False) for f in csv_files]
            df = pd.concat(dfs, ignore_index=True)
            print("Shape after CSV load:", df.shape)
            return df

        raise FileNotFoundError(f"No usable Feather or CSV files found in {dl_path}")

    def run(self, kind: str = "kagglehub") -> Path:
        self.paths.ensure()

        if kind == "kagglehub":
            df = self._load_from_kaggle()
        else:
            raise NotImplementedError("Currently only Kaggle ingestion is implemented")

        out = self.paths.processed / "loans_raw.parquet"
        write_parquet(df, out)
        print(f"[ingest] saved -> {out}, shape={df.shape}")
        return out
