import pandas as pd
from typing import List
from loanrisk_project.scoring.scorer import ScoringService
from loanrisk_project.scoring.pricing import PricingEngine

from models.models import CreditScore

from sqlmodel import Session

class CreditScoringService:
    """
    Service for credit scoring operations
    """
    def __init__(self):
        self.scorer = ScoringService(artifacts_dir="artifacts")
        self.pricer = PricingEngine()

    def score(self, data: pd.DataFrame, session: Session) -> List[CreditScore]:
        """
        Score credit data and return a list of CreditScore objects.

        This methods wraps the scoring and pricing logic from Branka's use case.

        :param data: DataFrame containing credit data
        :param session: Database session
        :return: List of CreditScore objects
        """
        result = self.scorer.predict_pd(data)
        offer = self.pricer.price_loans(
            result,
            amount_col="loan_amnt",
            term_col="term_months",
            pd_col="pd",
        )

        scores = [CreditScore(**row) for index, row in offer.iterrows()]

        session.add_all(scores)
        session.commit()

        return scores
        