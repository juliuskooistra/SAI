# scripts/train.py
from pathlib import Path
from loanrisk_project.core.config import Config
from loanrisk_project.core.paths import Paths
from loanrisk_project.modeling.trainer import Trainer

def main():
    repo_root = Path(__file__).resolve().parents[1]     # .../Use_Case_II
    config_path = repo_root / "config.yaml"

    cfg = Config(str(config_path))
    paths = Paths(cfg.raw_dir, cfg.processed_dir, cfg.artifacts_dir)

    res = Trainer(cfg, paths).train()
    print("[train] result:", res)
    print(f"[train] run_dir: {res['run_dir']}")
    print(f"[train] model  : {res['model_path']}")

if __name__ == "__main__":
    main()
