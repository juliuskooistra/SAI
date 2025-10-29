from __future__ import annotations
import re
from typing import Tuple
import numpy as np
import pandas as pd

# ---------- string/number parsers ----------

def pct_to_float(x) -> float | np.floating | np.nan:
    """
    '13.5%' -> 0.135 ;  '0.135' -> 0.135 ;  13.5 -> 0.135 ; None/'' -> np.nan
    """
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    s = str(x).strip()
    if s == "":
        return np.nan
    if s.endswith("%"):
        try:
            return float(s[:-1].replace(",", "").strip()) / 100.0
        except ValueError:
            return np.nan
    try:
        v = float(s.replace(",", ""))
        # if user passed whole percent like 13.5, assume % and scale
        return v / 100.0 if v > 1 else v
    except ValueError:
        return np.nan


def currency_to_float(x) -> float | np.floating | np.nan:
    """
    '$12,345.67' -> 12345.67 ; '12345' -> 12345.0 ; None/'' -> np.nan
    """
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    s = str(x).strip()
    if s == "":
        return np.nan
    s = s.replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return np.nan


def term_to_months(x) -> float | np.nan:
    """
    '36 months' -> 36 ; '60' -> 60 ; None -> nan
    """
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    m = re.search(r"(\d+)", str(x))
    return float(m.group(1)) if m else np.nan


def employment_length_to_years(x) -> float | np.nan:
    """
    '10+ years' -> 10.0 ; '< 1 year' -> 0.5 ; '3 years' -> 3.0 ; None -> nan
    """
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    s = str(x).strip().lower()
    if s in {"", "n/a", "none"}:
        return np.nan
    if "10+" in s:
        return 10.0
    if "<" in s:
        return 0.5
    m = re.search(r"(\d+)", s)
    return float(m.group(1)) if m else np.nan


def months_between(d1: pd.Timestamp, d2: pd.Timestamp) -> float | np.nan:
    """
    Calendar-month difference (ignores day-of-month for simplicity).
    """
    if pd.isna(d1) or pd.isna(d2):
        return np.nan
    return (d2.year - d1.year) * 12 + (d2.month - d1.month)

# ---------- winsorization ----------

def winsorize_col(s: pd.Series, q_lo: float, q_hi: float) -> Tuple[pd.Series, Tuple[float | None, float | None]]:
    """
    Cap series at given quantiles. Returns (capped_series, (lo_cap, hi_cap)).
    """
    lo, hi = s.quantile(q_lo), s.quantile(q_hi)
    if pd.notna(lo):
        s = s.mask(s < lo, lo)
    if pd.notna(hi):
        s = s.mask(s > hi, hi)
    return s, (None if pd.isna(lo) else float(lo), None if pd.isna(hi) else float(hi))
