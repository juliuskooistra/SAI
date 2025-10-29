import pandas as pd
import joblib
from pathlib import Path
from sqlmodel import Session, select
from loanrisk_project.portfolio.optimizer import PortfolioService, PortfolioConstraints

from models.models import PortfolioRequest, PortfolioResponse, CreditScore


class PortfolioOptimizationService:
    """
    Service for portfolio optimization operations

    Please note: memory heavy operations, not suitable for large datasets. There is much room for optimization of this function. In an ideal world, one would avoid pandas.
    """
    def optimize_portfolio(self, request: PortfolioRequest, session: Session) -> PortfolioResponse:

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

        offers = session.exec(select(CreditScore)).all()  # Example query to fetch offers with non-null APR

        # change offers to a dataframe
        offers = pd.DataFrame([offer.__dict__ for offer in offers])

        portfolio, summary = PortfolioService(constraints=constraints).select(offers)

        # change portfolio back to a list of CreditScoreResponses
        portfolio = [CreditScore(**row) for index, row in portfolio.iterrows()]

        return PortfolioResponse(portfolio=portfolio, summary=summary)