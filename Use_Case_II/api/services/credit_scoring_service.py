import pandas as pd
import joblib
from pathlib import Path

from loanrisk_project.scoring.scorer import ScoringService
from loanrisk_project.scoring.pricing import PricingEngine

from models.models import CreditScoreListRequest, CreditScoreRequest, CreditScoreResponse, CreditScoreListResponse, CreditScore

from database import get_db
from fastapi import Depends
from sqlmodel import Session

class CreditScoringService:
    """
    Service for credit scoring operations
    """
    def __init__(self):
        self.scorer = ScoringService(artifacts_dir="artifacts")
        self.pricer = PricingEngine()

    def score(self, request: CreditScoreRequest, session: Session) -> CreditScoreResponse:
        data = pd.DataFrame([request.dict()])
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
        session.refresh(scores[0])

        return CreditScoreResponse.model_validate(scores[0], from_attributes=True)

    def score_batch(self, request: CreditScoreListRequest, session: Session) -> CreditScoreListResponse:
        df = pd.DataFrame([item.dict() for item in request.data])
        result = self.scorer.predict_pd(df)
        offers = self.pricer.price_loans(
            result,
            amount_col="loan_amnt",
            term_col="term_months",
            pd_col="pd",
        )

        scores = [CreditScore(**row) for index, row in offers.iterrows()]
        session.add_all(scores)
        session.commit()

        return CreditScoreListResponse(data=scores)