"""
Billing router for token management and usage analytics.
"""

from fastapi import APIRouter, HTTPException, Request, Depends, status
from typing import Optional
from sqlmodel import Session
from datetime import datetime

from models.models import (
    TokenPurchaseRequest, TokenPurchaseResponse,
    UsageStatsRequest, UsageStatsResponse, RateLimitStatus, EndpointUsage, BalanceResponse
)
from services.billing_service import BillingService
from services.rate_limit_service import RateLimitService
from database import get_db


def get_authenticated_user(request: Request) -> tuple[str, Optional[int]]:
    """
    Get current user ID and API key ID from request state (set by AuthenticationMiddleware).
    
    :param request: FastAPI request object
    :return: Tuple of (user_id, api_key_id)
    :raises HTTPException: If authentication not found
    """
    if not hasattr(request.state, 'user_id') or not request.state.user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required (middleware not properly configured)",
        )
    
    user_id = request.state.user_id
    api_key_id = getattr(request.state, 'api_key_id', None)
    
    return user_id, api_key_id


class BillingRouter:
    """
    Router for billing, token management, and usage analytics.
    Authentication is handled by AuthenticationMiddleware.
    """

    def __init__(self):
        self.router = APIRouter()
        self.billing_service = BillingService()
        self.rate_limit_service = RateLimitService()
        self._register_routes()

    def _register_routes(self):
        """Register all billing routes."""
        self.router.post("/purchase-tokens", response_model=TokenPurchaseResponse)(self.purchase_tokens)
        self.router.get("/balance", response_model=BalanceResponse)(self.get_balance)
        self.router.get("/usage-stats", response_model=UsageStatsResponse)(self.get_usage_stats)
        self.router.get("/rate-limit-status", response_model=RateLimitStatus)(self.get_rate_limit_status)

    def purchase_tokens(self, 
                       request: TokenPurchaseRequest,
                       req: Request,
                       db: Session = Depends(get_db)) -> TokenPurchaseResponse:
        """
        Purchase tokens for the authenticated user.
        
        :param request: Token purchase request
        :param req: FastAPI request object (contains user auth from middleware)
        :param db: Database session
        :return: Purchase response
        :raises HTTPException: If purchase fails
        """
        user_id, _ = get_authenticated_user(req)
        
        if request.amount <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Token amount must be positive"
            )

        if request.amount > 10000:  # Reasonable limit for demo
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum token purchase is 10,000 tokens"
            )

        # For demo purposes, simulate payment processing
        transaction_id = f"demo_txn_{user_id}_{int(datetime.utcnow().timestamp())}"
        
        success = self.billing_service.add_tokens(
            user_id=user_id,
            amount=request.amount,
            transaction_type="purchase",
            description=f"Token purchase via {request.payment_method}",
            db=db
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to process token purchase"
            )

        # Get new balance
        new_balance = self.billing_service.get_user_balance(user_id, db)

        return TokenPurchaseResponse(
            message="Tokens purchased successfully",
            tokens_added=request.amount,
            new_balance=new_balance,
            transaction_id=transaction_id
        )

    def get_balance(self,
                   req: Request,
                   db: Session = Depends(get_db)) -> BalanceResponse:
        """
        Get current token balance for the authenticated user.
        
        :param req: FastAPI request object (contains user auth from middleware)
        :param db: Database session
        :return: Balance information
        """
        user_id, _ = get_authenticated_user(req)
        
        balance = self.billing_service.get_user_balance(user_id, db)
        if balance is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # Get additional user info
        from models.models import User
        user = db.query(User).filter(User.user_id == user_id).first()
        
        return {
            "current_balance": balance,
            "total_purchased": user.total_tokens_purchased,
            "total_used": user.total_tokens_used,
            "username": user.username
        }

    def get_usage_stats(self,
                       req: Request,
                       days: int = 30,
                       db: Session = Depends(get_db)) -> UsageStatsResponse:
        """
        Get usage statistics for the authenticated user.
        
        :param req: FastAPI request object (contains user auth from middleware)
        :param days: Number of days to look back
        :param db: Database session
        :return: Usage statistics
        """
        user_id, _ = get_authenticated_user(req)
        
        if days <= 0 or days > 365:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Days must be between 1 and 365"
            )

        stats = self.billing_service.get_usage_stats(user_id, days, db)
        
        return UsageStatsResponse(
            period_days=stats["period_days"],
            current_balance=stats["current_balance"],
            total_requests=stats["total_requests"],
            total_tokens_consumed=stats["total_tokens_consumed"],
            endpoint_breakdown=[
                EndpointUsage(
                    endpoint=item["endpoint"],
                    requests=item["requests"],
                    tokens=item["tokens"]
                )
                for item in stats["endpoint_breakdown"]
            ]
        )

    def get_rate_limit_status(self,
                             req: Request,
                             db: Session = Depends(get_db)) -> RateLimitStatus:
        """
        Get current rate limit status for the authenticated user.
        
        :param req: FastAPI request object (contains user auth from middleware)
        :param db: Database session
        :return: Rate limit status
        """
        user_id, api_key_id = get_authenticated_user(req)
        
        status_data = self.rate_limit_service.get_rate_limit_status(user_id, api_key_id, db)
        
        return RateLimitStatus(
            limits=status_data["limits"],
            current_usage=status_data["current_usage"],
            remaining=status_data["remaining"]
        )
