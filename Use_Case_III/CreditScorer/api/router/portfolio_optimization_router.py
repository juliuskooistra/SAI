from fastapi import APIRouter, Request, Depends
from sqlmodel import Session, select
from models.models import PortfolioRequest, PortfolioResponse, CreditScore
from loanrisk_project.portfolio.optimizer import PortfolioService, PortfolioConstraints
import pandas as pd
from database import get_db

class PortfolioOptimizationRouter:
    def __init__(self):
        self.router = APIRouter()
        self._register_routes()

    def _register_routes(self):
        """
        Register the peak voltage prediction routes.
        Authentication, billing, and rate limiting are handled by middleware.
        """
        self.router.post("/optimize-portfolio", response_model=PortfolioResponse)(self.get_optimized_portfolio)


    def get_optimized_portfolio(self, request: PortfolioRequest, req: Request, session: Session = Depends(get_db)) -> PortfolioResponse:
        """
        Get optimized portfolio data.

        Authentication, billing, and rate limiting are automatically handled by the 
        BillingRateLimitMiddleware before this endpoint is reached.

        Note: I'm being rather lazy here and directly using the PortfolioService from loanrisk_project from Branka's use case.
        If we have multiple paths in the router that need portfolio optimization, we might want to refactor this into a dedicated service class.
        For now this will suffice.
        """
        constraints = PortfolioConstraints(
            budget=request.budget,
            note_size=request.note_size,
            max_weight=request.max_weight,
            min_loans=request.min_loans,
            grade_cap=request.grade_cap,
            state_cap=request.state_cap,
            id_col="loan_id",
            grade_col="grade",
            state_col="addr_state",
            apy_col="expected_investor_apy",
            apr_col="apr",
        )

        offers = session.exec(select(CreditScore).where(CreditScore.apr > 0)).all()  # Example query to fetch offers with non-null APR

        # change offers to a dataframe
        offers = pd.DataFrame([offer.__dict__ for offer in offers])

        portfolio, summary = PortfolioService(constraints=constraints).select(offers)

        # change portfolio back to a list of CreditScoreResponses
        portfolio = [CreditScore(**row) for index, row in portfolio.iterrows()]
          
        return PortfolioResponse(portfolio=portfolio, summary=summary)
