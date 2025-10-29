from loanrisk_project.core.config import Config
from loanrisk_project.core.paths import Paths
from loanrisk_project.data.ingest import DataIngestor
from loanrisk_project.data.transform import FeatureEngineer

def main():
    cfg = Config("config.yaml")
    paths = Paths(cfg.raw_dir, cfg.processed_dir, cfg.artifacts_dir)
    paths.ensure()

    raw_path = DataIngestor(cfg, paths).run()
    print(f"[ingest]  saved -> {raw_path}")

    clean_path = FeatureEngineer(cfg, paths).run(raw_path)
    print(f"[transform] saved -> {clean_path}")

if __name__ == "__main__":
    main()
