from fastapi import APIRouter, Request, Depends
from sqlmodel import Session
from models.models import CreditScoreResponse, CreditScoreRequest, CreditScoreListRequest, CreditScoreListResponse
from services.credit_scoring_service import CreditScoringService
import pandas as pd
from database import get_db

class CreditScoringRouter:
    def __init__(self):
        self.router = APIRouter()
        self.credit_scoring_service = CreditScoringService()
        self._register_routes()

    def _register_routes(self):
        """
        Register the peak voltage prediction routes.
        Authentication, billing, and rate limiting are handled by middleware.
        """
        self.router.post("/credit-score", response_model=CreditScoreResponse)(self.get_credit_score)
        self.router.post("/credit-scores", response_model=CreditScoreListResponse)(self.get_credit_scores_batch)

    def get_credit_score(self, request: CreditScoreRequest, req: Request, session: Session = Depends(get_db)):
        """
        Get credit scores data.

        Authentication, billing, and rate limiting are automatically handled by the 
        BillingRateLimitMiddleware before this endpoint is reached.

        """
        df = pd.DataFrame([request.model_dump()])

        scores = self.credit_scoring_service.score(df, session)

        return CreditScoreResponse.model_validate(scores[0], from_attributes=True)

    def get_credit_scores_batch(self, request: CreditScoreListRequest, req: Request, session: Session = Depends(get_db)):
        """
        Get credit scores data for a batch of requests.

        Authentication, billing, and rate limiting are automatically handled by the
        BillingRateLimitMiddleware before this endpoint is reached.

        Note: only the creation of the dataframe is different from the single request version.
        """
        df = pd.DataFrame([item.model_dump() for item in request.data])

        scores = self.credit_scoring_service.score(df, session)

        return CreditScoreListResponse(data=[CreditScoreResponse.model_validate(score, from_attributes=True) for score in scores])