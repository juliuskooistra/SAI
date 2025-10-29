"""
Rate Limiting Middleware for FastAPI.

This middleware handles rate limiting checks for authenticated users.
Requires AuthenticationMiddleware to be applied first.
"""

from typing import Optional, Dict, Any
from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from sqlmodel import Session

from database import get_db
from services.rate_limit_service import RateLimitService


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Middleware that handles rate limiting for protected endpoints.
    Requires user authentication to be completed first.
    """

    def __init__(self, app, protected_paths: Optional[list] = None, excluded_paths: Optional[list] = None):
        """
        Initialize the rate limiting middleware.
        
        :param app: FastAPI application instance
        :param protected_paths: List of path prefixes that require rate limiting
        :param excluded_paths: List of specific paths to exclude from rate limiting
        """
        super().__init__(app)
        self.rate_limit_service = RateLimitService()
        
        # Default protected paths - only API endpoints need rate limiting
        self.protected_paths = protected_paths or ["/api/"]
        
        # Exclude billing and auth endpoints from rate limiting
        self.excluded_paths = excluded_paths or [
            "/auth/", "/billing/",  # Don't rate limit auth/billing operations
            "/docs", "/redoc", "/openapi.json",  # Documentation
            "/favicon.ico", "/health", "/status"  # Health checks
        ]

    def _requires_rate_limiting(self, path: str) -> bool:
        """Check if an endpoint requires rate limiting."""
        # Check specific exclusions first
        for excluded in self.excluded_paths:
            if path.startswith(excluded):
                return False
        
        # Check if path matches protected patterns
        for protected in self.protected_paths:
            if path.startswith(protected):
                return True
                
        return False

    def _check_rate_limits(self, user_id: str, api_key_id: Optional[int], db: Session) -> Dict[str, Any]:
        """Check if request is within rate limits."""
        return self.rate_limit_service.check_rate_limit(user_id, api_key_id, db)

    async def dispatch(self, request: Request, call_next):
        """Main rate limiting middleware logic."""
        path = request.url.path
        
        # Skip non-rate-limited endpoints
        if not self._requires_rate_limiting(path):
            response = await call_next(request)
            return response

        # Check if user is authenticated (should be set by AuthenticationMiddleware)
        if not hasattr(request.state, 'user_id') or not request.state.user_id:
            return Response(
                content='{"detail":"Authentication required for rate limiting"}',
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"Content-Type": "application/json"}
            )

        # Get database session
        db_generator = get_db()
        db = next(db_generator)
        
        try:
            user_id = request.state.user_id
            api_key_id = getattr(request.state, 'api_key_id', None)

            # Check rate limits
            rate_limit_result = self._check_rate_limits(user_id, api_key_id, db)
            if not rate_limit_result["allowed"]:
                error_detail = (
                    f"Rate limit exceeded for {rate_limit_result.get('limit_exceeded', 'unknown')} window. "
                    f"Current: {rate_limit_result.get('current_count', 0)}/{rate_limit_result.get('limit', 0)}"
                )
                return Response(
                    content=f'{{"detail":"{error_detail}"}}',
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers={"Retry-After": "60", "Content-Type": "application/json"}
                )

            # Continue to next middleware or endpoint
            response = await call_next(request)
            return response
                
        except Exception as e:
            # Handle any rate limiting exceptions
            return Response(
                content=f'{{"detail":"Rate limiting error: {str(e)}"}}',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                headers={"Content-Type": "application/json"}
            )
        finally:
            # Close database session
            db.close()


class RateLimitConfig:
    """Configuration helper for rate limiting middleware."""
    
    @staticmethod
    def create_middleware(protected_paths: list = None, excluded_paths: list = None):
        """Create a configured rate limiting middleware instance."""
        return RateLimitMiddleware(
            app=None,  # Will be set by FastAPI
            protected_paths=protected_paths or ["/api/"],
            excluded_paths=excluded_paths or ["/auth/", "/billing/"]
        )
