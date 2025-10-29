# loanrisk_project/scoring/pricing.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict
import numpy as np
import pandas as pd
import re

_DEFAULT_CFG = {
    # (pd_lo, pd_hi, grade, apr); REJECT -> apr=None
    "grade_buckets": [
        (0.00, 0.02, "A", 0.06),
        (0.02, 0.05, "B", 0.08),
        (0.05, 0.10, "C", 0.11),
        (0.10, 0.20, "D", 0.145),
        (0.20, 0.30, "E", 0.18),
        (0.30, 0.40, "F", 0.22),
        (0.40, 1.00, "REJECT", None),
    ],
    "origination_fee_by_grade": {"A": 0.01, "B": 0.015, "C": 0.02, "D": 0.025, "E": 0.03, "F": 0.04},
}

@dataclass
class PricingConfig:
    grade_buckets: list[tuple[float, float, str, float | None]]
    origination_fee_by_grade: dict[str, float]

    @classmethod
    def from_dict(cls, d: Dict[str, Any] | None = None) -> "PricingConfig":
        d = d or _DEFAULT_CFG
        return cls(
            grade_buckets=list(d["grade_buckets"]),
            origination_fee_by_grade=dict(d["origination_fee_by_grade"]),
        )

class PricingEngine:
    def __init__(self, cfg: PricingConfig | None = None) -> None:
        self.cfg = cfg or PricingConfig.from_dict()

    @staticmethod
    def _parse_term_months(x, default: int = 36) -> int:
        """Accept '36 months', 36, '36', NaN → int months, default if missing."""
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return default
        s = str(x).strip().lower()
        if s == "":
            return default
        m = re.search(r"(\d+)", s)
        try:
            return int(m.group(1)) if m else int(float(s))
        except Exception:
            return default

    @staticmethod
    def _safe_amount(row: pd.Series, primary: str) -> float | np.floating | np.nan:
        """Try primary amount col, fall back to common alternates."""
        for col in [primary, "loan_amnt", "funded_amnt", "funded_amnt_inv", "loan_amount"]:
            if col in row and pd.notna(row[col]):
                try:
                    return float(row[col])
                except Exception:
                    continue
        return np.nan

    @staticmethod
    def monthly_payment(principal: float | np.floating | np.nan, annual_rate: float | None, months: int) -> float | np.floating | np.nan:
        if annual_rate is None or pd.isna(principal) or months <= 0:
            return np.nan
        r = annual_rate / 12.0
        if r <= 0:
            return np.nan if pd.isna(principal) else principal / months
        try:
            return principal * (r * (1 + r) ** months) / ((1 + r) ** months - 1)
        except Exception:
            return np.nan

    def assign_grade_apr(self, pdv: float) -> tuple[str, float | None]:
        for lo, hi, grade, apr in self.cfg.grade_buckets:
            if lo <= pdv < hi:
                return grade, apr
        return "REJECT", None

    def price_loans(
        self,
        df: pd.DataFrame,
        amount_col: str = "loan_amnt",
        term_col: str = "term_months",
        pd_col: str = "pd",
    ) -> pd.DataFrame:
        out = df.copy()
        grades, aprs, fees, payments = [], [], [], []

        for _, row in out.iterrows():
            # PD → grade/APR
            pdv = float(row[pd_col])
            grade, apr = self.assign_grade_apr(pdv)
            grades.append(grade)

            # Amount (robust fallback)
            amt = self._safe_amount(row, amount_col)

            # Term months: prefer term_col; if missing/NaN, try 'term' string; else default 36
            raw_term = row.get(term_col, None)
            if (raw_term is None) or (isinstance(raw_term, float) and np.isnan(raw_term)):
                raw_term = row.get("term", None)
            term = self._parse_term_months(raw_term, default=36)

            if apr is None or pd.isna(amt):
                aprs.append(np.nan); fees.append(np.nan); payments.append(np.nan)
            else:
                aprs.append(apr)
                fee = self.cfg.origination_fee_by_grade.get(grade, 0.02)
                fees.append(fee)
                payments.append(self.monthly_payment(amt, apr, term))

        out["grade"] = grades
        out["apr"] = aprs
        out["origination_fee"] = fees
        out["monthly_payment"] = payments
        out["expected_investor_apy"] = (1 - out[pd_col]) * out["apr"] - out["origination_fee"].fillna(0)
        return out
