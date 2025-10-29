# common.py — minimal utilities used by 1.py

from __future__ import annotations
import re, yaml
from pathlib import Path
from typing import Dict, Any, Iterable, Tuple
import numpy as np
import pandas as pd

# ---------- FS / config ----------
def load_config(path: str | Path = "config.yaml") -> Dict[str, Any]:
    path = Path(path)
    with open(path, "r") as f:
        return yaml.safe_load(f)

def ensure_dirs(*dirs: Iterable[Path]) -> None:
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)

# ---------- Naming / parsing ----------
def norm_col(c: str) -> str:
    c = (c or "").strip()
    c = re.sub(r"[\s/.\-]+", "_", c)
    c = re.sub(r"[^0-9a-zA-Z_]", "", c)
    return c.lower()

def pct_to_float(x):
    if pd.isna(x): return np.nan
    s = str(x).strip()
    if s.endswith("%"):
        try: return float(s[:-1])
        except: return np.nan
    try: return float(s)
    except: return np.nan

def parse_term_months(s):
    if pd.isna(s): return np.nan
    m = re.search(r"(\d+)", str(s))
    return float(m.group(1)) if m else np.nan

def parse_emp_length(s):
    if pd.isna(s): return np.nan
    s = str(s).strip().lower()
    if s in ("n/a","nan","< 1 year","<1 year"): return 0.5
    if s.startswith("10+"): return 10.0
    m = re.search(r"(\d+)", s)
    return float(m.group(1)) if m else np.nan

def months_between(d1: pd.Timestamp, d2: pd.Timestamp):
    if pd.isna(d1) or pd.isna(d2): return np.nan
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)

# ---------- Winsorize ----------
def winsorize_col(s: pd.Series, q_lo: float, q_hi: float) -> Tuple[pd.Series, Tuple[float | None, float | None]]:
    lo, hi = s.quantile(q_lo), s.quantile(q_hi)
    if pd.notna(lo): s = s.mask(s < lo, lo)
    if pd.notna(hi): s = s.mask(s > hi, hi)
    return s, (None if pd.isna(lo) else float(lo), None if pd.isna(hi) else float(hi))
