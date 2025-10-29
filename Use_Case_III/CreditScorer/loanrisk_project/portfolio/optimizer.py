# loanrisk_project/portfolio/optimizer.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any, Tuple
import math
import numpy as np
import pandas as pd


@dataclass
class PortfolioConstraints:
    # Budgeting / sizing
    budget: float
    note_size: float = 100.0           # invest in fixed-size notes
    max_weight: float = 0.05           # per-loan max share of budget (e.g., 5%)
    min_loans: int = 20                # target # of distinct loans

    # Concentration caps (set to None to disable)
    grade_cap: float | None = 0.35     # max share for any single grade
    state_cap: float | None = 0.25     # max share for any single state

    # Column names (adjust if your dataset differs)
    id_col: str = "loan_id"
    grade_col: str = "grade"
    state_col: str = "addr_state"
    apy_col: str = "expected_investor_apy"  # produced by PricingEngine
    apr_col: str = "apr"                     # NaN => not investable


class PortfolioService:
    def __init__(self, constraints: PortfolioConstraints) -> None:
        self.c = constraints

    # ---------------- internal helpers ----------------

    def _units_left(self, total_cost: float) -> int:
        """How many notes can we still buy with remaining budget?"""
        return int((self.c.budget - total_cost) // self.c.note_size)

    def _max_units_per_loan(self) -> int:
        """Per-loan cap by weight constraint."""
        u = int(self.c.max_weight * self.c.budget / self.c.note_size)
        return max(u, 1)

    def _eligible(self, row: pd.Series) -> bool:
        """Skip loans without a price (apr NaN) or missing expected APY."""
        if self.c.apy_col not in row or pd.isna(row[self.c.apy_col]):
            return False
        if self.c.apr_col in row and pd.isna(row[self.c.apr_col]):
            return False
        return True

    def _cap_ok(
        self,
        selected: list[dict],
        row: pd.Series,
        counts_by_grade: Dict[str, int],
        counts_by_state: Dict[str, int],
    ) -> bool:
        """Ceiling-based cap check so the first few picks are allowed."""
        n_after = len(selected) + 1
        if n_after <= 1:
            return True  # always allow the very first pick

        # Grade cap
        if self.c.grade_cap is not None and self.c.grade_col in row.index:
            g = row[self.c.grade_col] if pd.notna(row[self.c.grade_col]) else "UNK"
            max_allowed = math.ceil(self.c.grade_cap * n_after)
            if counts_by_grade.get(g, 0) + 1 > max_allowed:
                return False

        # State cap
        if self.c.state_cap is not None and self.c.state_col in row.index:
            s = row[self.c.state_col] if pd.notna(row[self.c.state_col]) else "UNK"
            max_allowed = math.ceil(self.c.state_cap * n_after)
            if counts_by_state.get(s, 0) + 1 > max_allowed:
                return False

        return True

    # ---------------- public API ----------------

    def select(self, offers: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Greedy selection: sort by expected APY desc; buy up to max units/loan
        while respecting budget and (optionally) grade/state caps.
        Returns (portfolio_df, summary_dict).
        """
        if self.c.apy_col not in offers.columns:
            raise ValueError(f"offers must include '{self.c.apy_col}' (from PricingEngine).")

        # Work copy, drop rows we can’t price, sort by expected return
        df = offers.copy()
        df = df[df[self.c.apy_col].notna()].copy()
        if self.c.apr_col in df.columns:
            df = df[df[self.c.apr_col].notna()].copy()
        if df.empty:
            return pd.DataFrame(), {
                "total_cost": 0.0,
                "n_loans": 0,
                "budget": float(self.c.budget),
                "invested_pct": 0.0,
                "wtd_expected_apy": None,
            }

        df = df.sort_values(self.c.apy_col, ascending=False).reset_index(drop=True)

        # Ensure we have an ID
        if self.c.id_col not in df.columns:
            df[self.c.id_col] = df.index.astype(str)

        selected_rows: list[dict] = []
        counts_by_grade: Dict[str, int] = {}
        counts_by_state: Dict[str, int] = {}

        total_cost = 0.0
        max_units_each = self._max_units_per_loan()

        for _, row in df.iterrows():
            # Budget check
            if self._units_left(total_cost) <= 0:
                break

            # Skip uninvestable rows
            if not self._eligible(row):
                continue

            # Cap checks
            if not self._cap_ok(selected_rows, row, counts_by_grade, counts_by_state):
                continue

            # Units we can buy for this loan
            units_can_afford = self._units_left(total_cost)
            units = min(max_units_each, units_can_afford)
            if units <= 0:
                continue

            # Record selection
            r = row.to_dict()
            r["units"] = int(units)
            r["invested_amount"] = float(units * self.c.note_size)
            selected_rows.append(r)

            # Update totals
            total_cost += r["invested_amount"]

            # Update counts for caps
            if self.c.grade_col in row.index:
                g = row[self.c.grade_col] if pd.notna(row[self.c.grade_col]) else "UNK"
                counts_by_grade[g] = counts_by_grade.get(g, 0) + 1
            if self.c.state_col in row.index:
                s = row[self.c.state_col] if pd.notna(row[self.c.state_col]) else "UNK"
                counts_by_state[s] = counts_by_state.get(s, 0) + 1

            # Optional early stop: hit diversification target and no budget left for another full note
            if len(selected_rows) >= self.c.min_loans and self._units_left(total_cost) == 0:
                break

        # Build outputs
        portfolio = pd.DataFrame(selected_rows)
        if portfolio.empty:
            summary = {
                "total_cost": 0.0,
                "n_loans": 0,
                "budget": float(self.c.budget),
                "invested_pct": 0.0,
                "wtd_expected_apy": None,
            }
            return portfolio, summary

        portfolio["weight"] = portfolio["invested_amount"] / self.c.budget

        w = portfolio["invested_amount"]
        apy_col = self.c.apy_col
        wtd_apy = float((portfolio[apy_col] * w).sum() / w.sum()) if w.sum() else np.nan

        summary: Dict[str, Any] = {
            "total_cost": round(total_cost, 2),
            "n_loans": int(len(portfolio)),
            "budget": float(self.c.budget),
            "invested_pct": round(total_cost / self.c.budget, 4),
            "wtd_expected_apy": wtd_apy,
        }
        if self.c.grade_col in portfolio.columns:
            summary["by_grade"] = portfolio[self.c.grade_col].value_counts().to_dict()
        if self.c.state_col in portfolio.columns:
            summary["by_state"] = portfolio[self.c.state_col].value_counts().to_dict()

        return portfolio, summary
