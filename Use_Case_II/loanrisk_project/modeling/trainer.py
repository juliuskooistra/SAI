from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
import pandas as pd

from loanrisk_project.core.config import Config
from loanrisk_project.core.paths import Paths
from loanrisk_project.utils import read_parquet, write_json

class Trainer:
    """
    Trains an H2O AutoML binary classifier on loans_clean.parquet
    and saves a versioned artifact folder with:
      - leaderboard.csv
      - feature_columns.json  (features + target)
      - model_config.json     (hyperparams used)
      - the H2O model binary  (saved by h2o.save_model)
    """

    def __init__(self, cfg: Config, paths: Paths) -> None:
        self.cfg = cfg
        self.paths = paths

    def _choose_target(self, df: pd.DataFrame) -> str:
        # Prefer explicit target_default
        if "target_default" in df.columns:
            return "target_default"

        y_cols = [c for c in df.columns if c.startswith("y_") and c.endswith("m")]
        if not y_cols:
            if "y_12m" in df.columns:
                return "y_12m"
            raise ValueError("No target columns found (y_*m or target_default).")
        y_cols = sorted(y_cols, key=lambda c: int(c.split("_")[1][:-1]))
        return y_cols[-1]


    def train(self) -> Dict[str, Any]:
        # Lazy import so Python-only steps don’t require Java
        import h2o
        from h2o.automl import H2OAutoML

        data_path = self.paths.processed / "loans_clean.parquet"
        if not data_path.exists():
            raise FileNotFoundError(f"Missing {data_path}. Run FeatureEngineer first.")

        df = read_parquet(data_path)

        # Make a versioned run dir ONCE and reuse it
        run_dir = self.paths.artifacts / f"model_{pd.Timestamp.utcnow():%Y%m%d_%H%M%S}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # choose target + features
        y = self._choose_target(df)
        X: List[str] = [c for c in df.columns if c != y]

        # init H2O
        h2o.init()

        # Send to H2O
        hf = h2o.H2OFrame(df)
        hf[y] = hf[y].asfactor()  # classification

        # === Train/test split (e.g., 80/20) ===
        split_seed = self.cfg.get("split", "seed", default=42)
        train_ratio = self.cfg.get("split", "train_ratio", default=0.80)
        train, test = hf.split_frame([float(train_ratio)], seed=split_seed)

        # Export the splits into the SAME run_dir
        h2o.export_file(train, str(run_dir / "train.csv"), force=True)
        h2o.export_file(test,  str(run_dir / "test.csv"),  force=True)

        # AutoML params from config, with safe defaults
        aml = H2OAutoML(
            seed=self.cfg.get("automl", "seed", default=42),
            max_runtime_secs=self.cfg.get("automl", "max_runtime_secs", default=300),
            max_models=self.cfg.get("automl", "max_models", default=None),
            stopping_metric=self.cfg.get("automl", "stopping_metric", default="AUC"),
            sort_metric="AUC",
            nfolds=5,          # CV INSIDE TRAIN ONLY (no test leakage)
            verbosity="info",
        )

        # Train ONLY on train set
        aml.train(x=X, y=y, training_frame=train)

        leader = aml.leader
        leaderboard = aml.leaderboard.as_data_frame()

        # Evaluate on held-out test
        perf_test = leader.model_performance(test_data=test)
        test_auc = getattr(perf_test, "auc", lambda: None)()

        # Save leaderboard & metadata into the SAME run_dir
        leaderboard.to_csv(run_dir / "leaderboard.csv", index=False)
        write_json({"features": X, "target": y}, run_dir / "feature_columns.json")
        write_json(
            {
                "seed": self.cfg.get("automl", "seed", default=42),
                "stopping_metric": self.cfg.get("automl", "stopping_metric", default="AUC"),
                "max_runtime_secs": self.cfg.get("automl", "max_runtime_secs", default=300),
                "max_models": self.cfg.get("automl", "max_models", default=None),
                "split": {"train_ratio": float(train_ratio), "test_ratio": 1.0 - float(train_ratio), "seed": split_seed},
                "nfolds": 5,
                "test_auc": test_auc,
            },
            run_dir / "model_config.json",
        )

        # Save model binary to SAME run_dir
        model_path = h2o.save_model(model=leader, path=str(run_dir), force=True)

        return {
            "run_dir": str(run_dir),
            "model_path": model_path,
            "target": y,
            "n_features": len(X),
            "leaderboard_rows": int(leaderboard.shape[0]),
            "test_auc": test_auc,
        }
    