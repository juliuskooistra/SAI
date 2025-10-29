from pathlib import Path
import pandas as pd
from loanrisk_project.core.config import Config
from loanrisk_project.core.paths import Paths
from loanrisk_project.scoring.scorer import ScoringService
from loanrisk_project.scoring.pricing import PricingEngine

def main():
    cfg = Config("config.yaml")
    paths = Paths(cfg.raw_dir, cfg.processed_dir, cfg.artifacts_dir)
    paths.ensure()

    clean_path = paths.processed / "loans_clean.parquet"
    if not clean_path.exists():
        raise FileNotFoundError(f"Missing {clean_path}. Run scripts/ingest_transform.py first.")

    df = pd.read_parquet(clean_path)
    n = cfg.get("scoring", "max_rows", default=10000)
    if n:
        df = df.head(int(n))

    scored = ScoringService(paths.artifacts).predict_pd(df)
    offers = PricingEngine().price_loans(
        scored,
        amount_col=cfg.get("pricing", "amount_col", default="loan_amnt"),
        term_col=cfg.get("pricing", "term_col", default="term_months"),
        pd_col="pd",
    )

    ts = pd.Timestamp.utcnow().strftime("%Y%m%d_%H%M%S")
    out_parquet = paths.artifacts / f"offers_{ts}.parquet"
    out_csv = paths.artifacts / f"offers_{ts}.csv"
    offers.to_parquet(out_parquet, index=False)
    offers.to_csv(out_csv, index=False)
    print(f"[score]  saved -> {out_parquet}")
    print(f"[price]  saved -> {out_csv}")

if __name__ == "__main__":
    main()
