"""
Billing and rate limiting service for API usage management.
"""

from datetime import datetime, timedelta
from typing import Optional, Dict
from sqlmodel import Session, select
from sqlalchemy import and_, func

from models.models import User, APIUsage, TokenTransaction


class BillingService:
    """
    Service for managing user tokens, billing, and usage tracking.
    """
    def get_user(self, user_id: str, db: Session) -> Optional[User]:
        """Get current token balance for a user."""
        user = db.exec(select(User).where(User.user_id == user_id)).first()
        return user if user else None

    def get_user_balance(self, user_id: str, db: Session) -> Optional[float]:
        """Get current token balance for a user."""
        user = self.get_user(user_id, db)
        return user.token_balance if user else None

    def check_sufficient_balance(self, user_id: str, required_tokens: float, db: Session) -> bool:
        """Check if user has sufficient token balance."""
        balance = self.get_user_balance(user_id, db)
        return balance is not None and balance >= required_tokens

    def consume_tokens(self, user_id: str, api_key_id: int, endpoint: str, 
                      tokens_consumed: float, request_data: dict, db: Session) -> bool:
        """
        Consume tokens for an API request and log usage.
        
        :param user_id: User ID
        :param api_key_id: API Key ID
        :param endpoint: Endpoint being called
        :param tokens_consumed: Number of tokens to consume
        :param request_data: Request data for logging
        :param db: Database session
        :return: True if successful, False if insufficient balance
        """
        user = self.get_user(user_id, db)
        if not user or user.token_balance < tokens_consumed:
            return False

        # Deduct tokens
        previous_balance = user.token_balance
        user.token_balance -= tokens_consumed
        user.total_tokens_used += tokens_consumed
        
        # Log the transaction
        transaction = TokenTransaction(
            user_id=user_id,
            transaction_type="usage",
            amount=-tokens_consumed,
            previous_balance=previous_balance,
            new_balance=user.token_balance,
            description=f"API call to {endpoint}",
            reference_id=f"{api_key_id}_{endpoint}_{datetime.utcnow().isoformat()}"
        )
        db.add(transaction)

        # Log the usage
        usage = APIUsage(
            user_id=user_id,
            api_key_id=api_key_id,
            endpoint=endpoint,
            tokens_consumed=tokens_consumed,
            request_size=len(str(request_data)),
            success=True
        )
        db.add(usage)
        
        db.commit()
        return True

    def add_tokens(self, user_id: str, transaction_id: str, amount: float, transaction_type: str, 
                   description: str, db: Session) -> bool:
        """Add tokens to a user's account."""
        user = self.get_user(user_id, db)
        if not user:
            return False

        previous_balance = user.token_balance
        user.token_balance += amount
        
        if transaction_type == "purchase":
            user.total_tokens_purchased += amount

        # Log the transaction
        transaction = TokenTransaction(
            user_id=user_id,
            transaction_type=transaction_type,
            amount=amount,
            previous_balance=previous_balance,
            new_balance=user.token_balance,
            description=description,
            reference_id=transaction_id
        )
        db.add(transaction)
        db.commit()
        return True

    def get_usage_stats(self, user_id: str, days: int, db: Session) -> Dict:
        """Get usage statistics for a user over the last N days."""
        since = datetime.utcnow() - timedelta(days=days)
        
        # Get usage data
        usage_query = db.exec(select(APIUsage).where(
            and_(APIUsage.user_id == user_id, APIUsage.timestamp >= since)
        )).all()
        
        total_requests = len(usage_query)
        total_tokens = sum(item.tokens_consumed for item in usage_query) or 0
        
        # Get usage by endpoint
        endpoint_stats = db.exec(select(
            APIUsage.endpoint,
            func.count(APIUsage.id).label('requests'),
            func.sum(APIUsage.tokens_consumed).label('tokens')
        ).where(
            and_(APIUsage.user_id == user_id, APIUsage.timestamp >= since)
        ).group_by(APIUsage.endpoint)).all()

        # Get current balance
        user = self.get_user(user_id, db)
        
        return {
            "period_days": days,
            "current_balance": user.token_balance if user else 0,
            "total_requests": total_requests,
            "total_tokens_consumed": float(total_tokens),
            "endpoint_breakdown": [
                {
                    "endpoint": stat.endpoint,
                    "requests": stat.requests,
                    "tokens": float(stat.tokens or 0)
                }
                for stat in endpoint_stats
            ]
        }


