# scripts/ingest_transform.py
from pathlib import Path
from loanrisk_project.core.config import Config
from loanrisk_project.core.paths import Paths
from loanrisk_project.data.ingest import DataIngestor
from loanrisk_project.data.transform import FeatureEngineer

def main():
    repo_root = Path(__file__).resolve().parents[1]  # /Users/heb1/Documents/SAI/Use_Case_II
    config_path = repo_root / "config.yaml"

    cfg = Config(str(config_path))
    paths = Paths(cfg.raw_dir, cfg.processed_dir, cfg.artifacts_dir)
    paths.ensure()

    raw_path = DataIngestor(cfg, paths).run()
    print(f"[ingest]  saved -> {raw_path}")

    clean_path = FeatureEngineer(cfg, paths).run(raw_path)
    print(f"[transform] saved -> {clean_path}")

if __name__ == "__main__":
    main()

