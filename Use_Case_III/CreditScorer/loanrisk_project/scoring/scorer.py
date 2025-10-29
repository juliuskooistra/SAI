# loanrisk_project/scoring/scorer.py
from __future__ import annotations
from pathlib import Path
import pandas as pd

from loanrisk_project.modeling.registry import ModelRegistry
from loanrisk_project.utils import read_json


class ScoringService:
    """
    Load an H2O model from artifacts/, align feature columns to the training
    schema, and return a DataFrame with a 'pd' column.
    """

    def __init__(self, artifacts_dir: str | Path):
        self.registry = ModelRegistry(artifacts_dir)

    def _load_feature_manifest(self, run_dir: Path) -> tuple[list[str], str]:
        meta = read_json(run_dir / "feature_columns.json")
        feats = list(meta["features"])
        target = str(meta["target"])
        return feats, target

    def _find_model_file(self, run_dir: Path) -> str:
        candidates = sorted(
            [p for p in run_dir.iterdir() if p.is_file() and p.suffix not in (".csv", ".json")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            raise FileNotFoundError(f"No H2O model file found under {run_dir}")
        return str(candidates[0])

    def predict_pd(
        self,
        borrowers: pd.DataFrame,
        run_dir: str | Path | None = None,
        verbose: bool = False,
    ) -> pd.DataFrame:
        import h2o

        # Choose run deterministically (allow caller to pin it!)
        rdir = Path(run_dir) if run_dir else self.registry.latest_run()
        if not rdir:
            raise FileNotFoundError("No model run found in artifacts dir.")
        if verbose:
            print(f"[scoring] using run_dir = {rdir}")

        model_path = self._find_model_file(rdir)
        feature_cols, target = self._load_feature_manifest(rdir)

        # Align columns (order + presence)
        df = borrowers.copy()
        for c in feature_cols:
            if c not in df.columns:
                df[c] = pd.NA
        df = df[feature_cols]

        # Start H2O & load model
        h2o.init()
        model = h2o.load_model(model_path)

        # Training schema (names + domains). domains: None => numeric/time, list => categorical
        names = list(model._model_json["output"]["names"])
        domains = list(model._model_json["output"]["domains"])
        schema_map = {n: d for n, d in zip(names, domains)}

        # PRE-H2OFRAME: only coerce categoricals to string; leave numeric AND datetimes alone
        for col in feature_cols:
            dom = schema_map.get(col, None)
            if dom is not None:  # categorical in training
                df[col] = df[col].astype("string")

        # Build frame & HARD-COERCE only categoricals to factor on H2O side
        hf = h2o.H2OFrame(df)
        for col in feature_cols:
            dom = schema_map.get(col, None)
            if dom is not None:
                hf[col] = hf[col].asfactor()

        # Predict
        preds = model.predict(hf).as_data_frame()
        if "p1" in preds.columns:
            pd_series = preds["p1"]
        else:
            prob_cols = [c for c in preds.columns if c.lower().startswith("p")]
            pd_series = preds[prob_cols[-1]] if prob_cols else preds.iloc[:, -1]

        out = borrowers.copy()
        out["pd"] = pd_series.values

        if verbose:
            from pathlib import Path as _P
            print(f"[scoring] model: { _P(model_path).name }")
            q = out["pd"].quantile([0, .1, .25, .5, .75, .9, .99, 1.0])
            print("[scoring] PD quantiles:\n", q.to_string())

        return out
