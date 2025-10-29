from pathlib import Path
import json
import pandas as pd

from loanrisk_project.core.config import Config
from loanrisk_project.core.paths import Paths
from loanrisk_project.portfolio.optimizer import PortfolioService, PortfolioConstraints

def latest_offers(artifacts: Path) -> Path:
    files = sorted(artifacts.glob("offers_*.parquet"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError("No offers_*.parquet found in artifacts/. Run scripts/score_price.py first.")
    return files[0]

def main():
    # NEW: load config relative to .../Use_Case_II
    repo_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(repo_root / "config.yaml"))

    paths = Paths(cfg.raw_dir, cfg.processed_dir, cfg.artifacts_dir)
    paths.ensure()

    offers_path = latest_offers(paths.artifacts)
    offers = pd.read_parquet(offers_path)

    constraints = PortfolioConstraints(
        budget=float(cfg.get("portfolio", "budget", default=5000.0)),
        note_size=float(cfg.get("portfolio", "note_size", default=100.0)),
        max_weight=float(cfg.get("portfolio", "max_weight", default=0.05)),
        min_loans=int(cfg.get("portfolio", "min_loans", default=20)),
        grade_cap=cfg.get("portfolio", "grade_cap", default=0.5),
        state_cap=cfg.get("portfolio", "state_cap", default=None),
        id_col=cfg.get("portfolio", "id_col", default="loan_id"),
        grade_col=cfg.get("portfolio", "grade_col", default="grade"),
        state_col=cfg.get("portfolio", "state_col", default="addr_state"),
        apy_col=cfg.get("portfolio", "apy_col", default="expected_investor_apy"),
        apr_col=cfg.get("portfolio", "apr_col", default="apr"),
    )

    svc = PortfolioService(constraints)
    portfolio, summary = svc.select(offers)

    ts = pd.Timestamp.utcnow().strftime("%Y%m%d_%H%M%S")
    out_csv = paths.artifacts / f"portfolio_{ts}.csv"
    out_json = paths.artifacts / f"portfolio_{ts}_summary.json"
    portfolio.to_csv(out_csv, index=False)
    with open(out_json, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[portfolio] saved -> {out_csv}")
    print(f"[portfolio] summary -> {out_json}")
    print("[portfolio] summary:", summary)

if __name__ == "__main__":
    main()
