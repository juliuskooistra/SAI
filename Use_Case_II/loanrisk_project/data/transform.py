# loanrisk_project/data/transform.py
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np

from loanrisk_project.core.config import Config
from loanrisk_project.core.paths import Paths
from loanrisk_project.utils import write_parquet


class FeatureEngineer:
    """
    Clean, normalize, and feature-engineer LendingClub data.
    """

    def __init__(self, cfg: Config, paths: Paths):
        self.cfg = cfg
        self.paths = paths
        self.audit = {}  # metadata about cleaning, imputation, leakage

    # --- 1. Relevant feature subset ---
    # Not all featurs available in the data should be used for scoring. Only features available at the time of loan issuance should be used.
    def _select_relevant(self, df: pd.DataFrame) -> pd.DataFrame:
        keep_cols = [
            # loan + borrower application info
            "loan_amnt", "term", "int_rate", "installment", "grade", "sub_grade",
            "emp_title", "emp_length", "home_ownership", "annual_inc",
            "verification_status", "issue_d", "purpose", "title",
            "zip_code", "addr_state", "dti",
            # credit history at application
            "delinq_2yrs", "earliest_cr_line", "fico_range_low",
            "fico_range_high", "inq_last_6mths", "mths_since_last_delinq",
            "mths_since_last_record", "open_acc", "pub_rec", "revol_bal",
            "revol_util", "total_acc",
            # loan status (used to create target)
            "loan_status"
        ]
        df = df[keep_cols].copy()
        print(f"Subset to relevant features: {df.shape[1]} columns")
        return df

    # --- 2. Cleaning & Quality Checks ---
    # We: (1) drop duplicates, (2) replace sentinel values with NaN,
    # (3) audit missingness, (4) simple consistency checks (e.g., funded_amnt ≤ loan_amnt).
    def _clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        before = len(df)
        df = df.drop_duplicates()
        print(f"Dropped {before - len(df)} duplicates")

        # Replace sentinel values
        for col in df.select_dtypes(exclude="category"):
            df[col] = df[col].replace(
                [-1, "n/a", "N/A", "None", "null", ""], np.nan
            )

        # missingness audit
        missing = df.isna().mean().sort_values(ascending=False)
        high_missing = missing[missing > 0.8]
        self.audit["high_missing_cols"] = high_missing.index.tolist()
        if len(high_missing):
            print("High-missing cols (>80%):", high_missing.index.tolist())

        # simple consistency checks
        if "funded_amnt" in df and "loan_amnt" in df:
            bad = (df["funded_amnt"] > df["loan_amnt"]).sum()
            if bad:
                print(f"⚠ {bad} rows where funded_amnt > loan_amnt")

        if "funded_amnt_inv" in df and "funded_amnt" in df:
            bad = (df["funded_amnt_inv"] > df["funded_amnt"]).sum()
            if bad:
                print(f"⚠ {bad} rows where funded_amnt_inv > funded_amnt")

        return df

    # --- 3. Column Parsing & Normalization ---
    # We convert dates, percentages, and categorical variables to numeric formats.
    def _parse_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        # dates
        for col in ["issue_d", "earliest_cr_line"]:
            if col in df:
                df[col] = pd.to_datetime(df[col], errors="coerce")

        # percents
        if "int_rate" in df:
            df["int_rate"] = pd.to_numeric(
                df["int_rate"].astype(str).str.replace("%", ""), errors="coerce"
            )
        if "revol_util" in df:
            df["revol_util"] = pd.to_numeric(
                df["revol_util"].astype(str).str.replace("%", ""), errors="coerce"
            )

        # term → numeric months
        if "term" in df:
            df["term_months"] = df["term"].astype(str).str.extract(r"(\d+)").astype(float)

        # emp_length
        if "emp_length" in df:
            mapping = {
                "10+ years": 10,
                "9 years": 9,
                "8 years": 8,
                "7 years": 7,
                "6 years": 6,
                "5 years": 5,
                "4 years": 4,
                "3 years": 3,
                "2 years": 2,
                "1 year": 1,
                "< 1 year": 0.5,
                "n/a": np.nan,
            }
            df["emp_length_years"] = df["emp_length"].map(mapping)

        # fico midpoint
        if "fico_range_low" in df and "fico_range_high" in df:
            df["fico_mid"] = (df["fico_range_low"] + df["fico_range_high"]) / 2

        # credit history length
        if "issue_d" in df and "earliest_cr_line" in df:
            df["credit_hist_months"] = (
                (df["issue_d"] - df["earliest_cr_line"]).dt.days / 30.44
            )

        return df

    # --- 4. Feature Engineering ---
    # We create new features based on domain knowledge and prior research.
    def _engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        if "annual_inc" in df and "loan_amnt" in df:
            df["income_to_loan"] = df["annual_inc"] / df["loan_amnt"]

        if "revol_util" in df:
            df["revol_util_ratio"] = df["revol_util"] / 100.0

        if "dti" in df:
            df["dti_bucket"] = pd.cut(
                df["dti"],
                bins=[-np.inf, 10, 20, 30, np.inf],
                labels=["low", "medium", "high", "very_high"],
            )

        if "zip_code" in df:
            df["zip3"] = df["zip_code"].astype(str).str[:3]

        if "addr_state" in df:
            region_map = {
                "NY": "Northeast", "NJ": "Northeast",
                "CA": "West", "TX": "South", "FL": "South",
            }
            df["region"] = df["addr_state"].map(region_map).fillna("Other")

        return df

    # --- 5. Target ---
    # We create a binary target: 1 if defaulted/charged-off, 0 if fully paid.
    def _create_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        default_statuses = {
            "Charged Off", "Default", "Late (31-120 days)",
            "Does not meet the credit policy. Status:Charged Off",
        }
        paid_statuses = {
            "Fully Paid", "Does not meet the credit policy. Status:Fully Paid",
        }

        df["target_default"] = np.where(
            df["loan_status"].isin(default_statuses), 1,
            np.where(df["loan_status"].isin(paid_statuses), 0, np.nan)
        )

        before = len(df)
        df = df.dropna(subset=["target_default"])
        after = len(df)
        print(f"Dropped {before - after} ambiguous-status rows")

        df["target_default"] = df["target_default"].astype(int)
        # drop loan_status (avoid leakage in training)
        df = df.drop(columns=["loan_status"])

        return df

        # --- 6. Quality Enforcement ---
    # We winsorize, ensure numeric types, and impute missing values.
    def _enforce_quality(self, df: pd.DataFrame) -> pd.DataFrame:
        # winsorize annual_inc
        if "annual_inc" in df:
            cap = df["annual_inc"].quantile(0.99)
            df.loc[df["annual_inc"] > cap, "annual_inc"] = cap
            self.audit["annual_inc_cap"] = float(cap)

        # ensure numeric columns are float
        for col in df.select_dtypes(include=["Int64", "int64", "float64"]).columns:
            df[col] = df[col].astype(float)

        # impute numeric
        for col in df.select_dtypes(include=[np.number]):
            if df[col].isna().any():
                median = df[col].median()
                df[col] = df[col].fillna(median)
                self.audit[f"impute_{col}"] = float(median)

        # impute categorical
        for col in df.select_dtypes(include=["object", "category"]):
            if df[col].isna().any():
                mode = df[col].mode().iloc[0] if not df[col].mode().empty else "Unknown"
                df[col] = df[col].fillna(mode)
                self.audit[f"impute_{col}"] = str(mode)

        return df

    # --- Additional Helper  ---
    # We prune high-cardinality categorical features to reduce noise and overfitting. Ex. emp_title has >460k unique values.
    def _prune_high_cardinality(self, df: pd.DataFrame, max_levels: int = 50) -> pd.DataFrame:
        """
        Reduce or drop high-cardinality categorical features.
        Keeps top-N most frequent categories, rest -> 'Other'.
        """
        cat_cols = df.select_dtypes(include=["object", "category"]).columns
        for col in cat_cols:
            n_levels = df[col].nunique()
            if n_levels > max_levels:
                top_levels = df[col].value_counts().nlargest(max_levels).index

                # ensure string type (avoid Categorical issues)
                df[col] = df[col].astype(str)

                # assign Other for rare categories
                df[col] = df[col].where(df[col].isin(top_levels), "Other")

                # cast back to categorical
                df[col] = df[col].astype("category")

                self.audit[f"pruned_{col}"] = int(n_levels)
        return df


    # --- Orchestration ---
    def run(self, src: Path | None = None) -> Path:
        self.paths.ensure()
        src = src or (self.paths.processed / "loans_raw.parquet")
        if not src.exists():
            raise FileNotFoundError(f"Missing source parquet: {src}")

        df = pd.read_parquet(src)
        df = self._select_relevant(df)   
        df = self._clean_data(df)
        df = self._parse_columns(df)
        df = self._engineer_features(df)
        df = self._prune_high_cardinality(df)
        df = self._create_labels(df)
        df = self._enforce_quality(df)

        out = self.paths.processed / "loans_clean.parquet"
        write_parquet(df, out)
        print(f"[transform] saved -> {out}, shape={df.shape}")
        return out
    
    