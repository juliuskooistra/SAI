from typing import Optional, Dict
from datetime import datetime, timedelta
from sqlmodel import Session, select
from sqlalchemy import and_

from ..models.models import User, APIKey, APIUsage


class RateLimitService:
    """
    Service for managing API rate limiting.
    """
    def _get_user(self, user_id: str, db: Session) -> Optional[User]:
        """Get user by user_id."""
        user = db.exec(select(User).where(User.user_id == user_id)).first()
        return user if user else None
    
    def _get_api_key(self, api_key_id: int, db: Session) -> Optional[APIKey]:
        """Get API key by ID."""
        api_key = db.exec(select(APIKey).where(APIKey.id == api_key_id)).first()
        return api_key if api_key else None
    
    def _get_request_count(self, user_id: str, api_key_id: Optional[int], since: datetime, db: Session) -> int:
        """
        Get the count of successful requests made by a user (and optionally API key) since a given time.
        
        :param user_id: User ID
        :param api_key_id: Optional API Key ID
        :param since: Datetime to count requests since
        :param db: Database session
        :return: Count of requests
        """
        query = select(APIUsage).where(
            and_(
                APIUsage.user_id == user_id,
                APIUsage.timestamp >= since,
                APIUsage.success == True
            )
        )
        
        if api_key_id:
            query = query.where(APIUsage.api_key_id == api_key_id)

        return len(db.exec(query).all())

    def check_rate_limit(self, user_id: str, api_key_id: Optional[int], db: Session) -> Dict[str, bool]:
        """
        Check if user/key is within rate limits for all time windows.
        
        :param user_id: User ID
        :param api_key_id: Optional API Key ID for key-specific limits
        :param db: Database session
        :return: Dict with rate limit status for each window
        """
        # Get user and API key limits
        user = self._get_user(user_id, db)
        if not user:
            return {"allowed": False, "reason": "User not found"}

        api_key = None
        if api_key_id:
            api_key = self._get_api_key(api_key_id, db)

        # Check each time window
        windows = {
            "minute": {"limit": api_key.requests_per_minute if api_key and api_key.requests_per_minute else user.requests_per_minute, "duration": 60},
            "hour": {"limit": api_key.requests_per_hour if api_key and api_key.requests_per_hour else user.requests_per_hour, "duration": 3600},
            "day": {"limit": api_key.requests_per_day if api_key and api_key.requests_per_day else user.requests_per_day, "duration": 86400}
        }

        print(windows)  # Debugging line

        results = {"allowed": True}
        
        for window_type, config in windows.items():
            window_start = datetime.utcnow() - timedelta(seconds=config["duration"])
            
            # Count requests in this window
            request_count = self._get_request_count(user_id, api_key_id, window_start, db)

            print(config["limit"], request_count)
            
            if request_count >= config["limit"]:
                results["allowed"] = False
                results["limit_exceeded"] = window_type
                results["current_count"] = request_count
                results["limit"] = config["limit"]
                break
            else:
                results[f"{window_type}_usage"] = f"{request_count}/{config['limit']}"

        return results

    def record_request(self, user_id: str, api_key_id: Optional[int], db: Session):
        """Record a request for rate limiting purposes (handled by APIUsage table)."""
        # Rate limiting is tracked through the APIUsage table
        # This method is here for consistency but actual recording happens in BillingService
        pass

    def get_rate_limit_status(self, user_id: str, api_key_id: Optional[int], db: Session) -> Dict:
        """Get current rate limit status and remaining requests."""
        user = self._get_user(user_id, db)
        if not user:
            return {"error": "User not found"}

        api_key = None
        if api_key_id:
            api_key = self._get_api_key(api_key_id, db)

        # Get limits
        limits = {
            "requests_per_minute": api_key.requests_per_minute if api_key and api_key.requests_per_minute else user.requests_per_minute,
            "requests_per_hour": api_key.requests_per_hour if api_key and api_key.requests_per_hour else user.requests_per_hour,
            "requests_per_day": api_key.requests_per_day if api_key and api_key.requests_per_day else user.requests_per_day
        }

        # Get current usage
        now = datetime.utcnow()
        windows = {
            "minute": now - timedelta(minutes=1),
            "hour": now - timedelta(hours=1), 
            "day": now - timedelta(days=1)
        }

        current_usage = {}
        remaining = {}

        for window_name, window_start in windows.items():
            count = self._get_request_count(user_id, api_key_id, window_start, db)
            limit_key = f"requests_per_{window_name}"
            current_usage[window_name] = count
            remaining[window_name] = max(0, limits[limit_key] - count)

        return {
            "limits": limits,
            "current_usage": current_usage,
            "remaining": remaining
        }
