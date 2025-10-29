from fastapi import APIRouter, Request, Depends
from sqlmodel import Session
from models.models import PortfolioRequest, PortfolioResponse
from services.portfolio_optimization_service import PortfolioOptimizationService
from database import get_db

class PortfolioOptimizationRouter:
    def __init__(self):
        self.router = APIRouter()
        self.portfolio_optimization_service = PortfolioOptimizationService()
        self._register_routes()

    def _register_routes(self):
        """
        Register the peak voltage prediction routes.
        Authentication, billing, and rate limiting are handled by middleware.
        """
        self.router.post("/optimize-portfolio", response_model=PortfolioResponse)(self.get_optimized_portfolio)

    def get_optimized_portfolio(self, request: PortfolioRequest, req: Request, session: Session = Depends(get_db)):
        """
        Get optimized portfolio data.

        Authentication, billing, and rate limiting are automatically handled by the 
        BillingRateLimitMiddleware before this endpoint is reached.
        """
        return self.portfolio_optimization_service.optimize_portfolio(request, session)

