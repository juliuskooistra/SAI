# LoanRisk Project

Modular pipeline for ingesting Lending data, feature engineering, AutoML training (H2O), scoring PDs, pricing loans, and constructing portfolios.

## Project Layout

├─ loanrisk_project/ # reusable library (importable)
│ ├─ core/
│ ├─ data/
│ ├─ modeling/
│ ├─ scoring/
│ ├─ portfolio/
│ └─ init.py
├─ scripts/ # CLI runners
│ ├─ ingest_transform.py
│ ├─ train.py
│ ├─ score_price.py
│ └─ portfolio.py
├─ data/
│ ├─ raw/
│ └─ processed/
├─ artifacts/
├─ config.yaml
├─ requirements.txt
├─ pyproject.toml
└─ README.md


## Quickstart

```bash
# 1) Create env and install (editable)
pip install -e .

# 2) Run the pipeline
python scripts/ingest_transform.py
python scripts/train.py
python scripts/score_price.py
python scripts/portfolio.py

Outputs:

data/processed/loans_raw.parquet, loans_clean.parquet
artifacts/model_*/ (leaderboard, model_config.json, feature_columns.json, H2O model)
artifacts/offers_*.{parquet,csv}
artifacts/portfolio_*.csv, portfolio_*_summary.json
