"""
Authentication Middleware for FastAPI.

This middleware handles API key validation and user authentication.
It adds user context to the request state for downstream use.
"""

import hashlib
from typing import Optional, Tuple
from fastapi import Request, Response, status
from fastapi.security.utils import get_authorization_scheme_param
from starlette.middleware.base import BaseHTTPMiddleware
from sqlmodel import Session, select

from ..database import get_db
from ..models.models import APIKey
from ..services.auth_service import AuthService


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """
    Middleware that handles API key authentication for protected endpoints.
    """

    def __init__(self, app, protected_paths: Optional[list] = None, excluded_paths: Optional[list] = None):
        """
        Initialize the authentication middleware.
        
        :param app: FastAPI application instance
        :param protected_paths: List of path prefixes that require authentication
        :param excluded_paths: List of specific paths to exclude from authentication
        """
        super().__init__(app)
        self.auth_service = AuthService()
        
        # Default protected paths - anything that needs authentication
        self.protected_paths = protected_paths or ["/api/", "/billing/"]
        
        # Always excluded paths - public endpoints
        self.excluded_paths = excluded_paths or [
            "/auth/register", "/auth/login",  # Authentication endpoints
            "/docs", "/redoc", "/openapi.json",  # Documentation
            "/favicon.ico", "/health", "/status"  # Health checks
        ]

    def _requires_authentication(self, path: str) -> bool:
        """Check if an endpoint requires authentication."""
        # Check specific exclusions first
        for excluded in self.excluded_paths:
            if path == excluded or path.startswith(excluded):
                return False
        
        # Check if path matches protected patterns
        for protected in self.protected_paths:
            if path.startswith(protected):
                return True
                
        return False

    def _extract_api_key(self, request: Request) -> Optional[str]:
        """Extract API key from Authorization header."""
        authorization = request.headers.get("Authorization")
        if not authorization:
            return None
            
        scheme, param = get_authorization_scheme_param(authorization)
        if scheme.lower() != "bearer":
            return None
            
        return param

    def _authenticate_request(self, api_key: str, db: Session) -> Tuple[Optional[str], Optional[int]]:
        """
        Authenticate API key and return user_id and api_key_id.
        
        :param api_key: The API key from request
        :param db: Database session
        :return: Tuple of (user_id, api_key_id) or (None, None) if invalid
        """
        user_id = self.auth_service.validate_api_key(api_key, db)
        if not user_id:
            return None, None
            
        # Get API key record for downstream use
        hashed_key = hashlib.sha256(f"{api_key}{self.auth_service.api_key_secret}".encode('utf-8')).hexdigest()
        api_key_record = db.exec(select(APIKey).filter(APIKey.hashed_key == hashed_key)).first()
        api_key_id = api_key_record.id if api_key_record else None
        
        return user_id, api_key_id

    async def dispatch(self, request: Request, call_next):
        """Main authentication middleware logic."""
        path = request.url.path
        
        # Skip non-protected endpoints
        if not self._requires_authentication(path):
            response = await call_next(request)
            return response

        # Get database session
        db_generator = get_db()
        db = next(db_generator)
        
        try:
            # Extract and validate API key
            api_key = self._extract_api_key(request)
            if not api_key:
                return Response(
                    content='{"detail":"Missing API key"}',
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    headers={"WWW-Authenticate": "Bearer", "Content-Type": "application/json"}
                )

            # Authenticate user
            user_id, api_key_id = self._authenticate_request(api_key, db)
            if not user_id:
                return Response(
                    content='{"detail":"Invalid or expired API key"}',
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    headers={"WWW-Authenticate": "Bearer", "Content-Type": "application/json"}
                )

            # Add user context to request state for downstream use
            request.state.user_id = user_id
            request.state.api_key_id = api_key_id
            request.state.authenticated = True

            # Continue to next middleware or endpoint
            response = await call_next(request)
            return response
                
        except Exception as e:
            # Handle any authentication-level exceptions
            return Response(
                content=f'{{"detail":"Authentication error: {str(e)}"}}',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                headers={"Content-Type": "application/json"}
            )
        finally:
            # Close database session
            db.close()


class AuthenticationConfig:
    """Configuration helper for authentication middleware."""
    
    @staticmethod
    def create_middleware(protected_paths: list = None, excluded_paths: list = None):
        """Create a configured authentication middleware instance."""
        return AuthenticationMiddleware(
            app=None,  # Will be set by FastAPI
            protected_paths=protected_paths or ["/api/", "/billing/"],
            excluded_paths=excluded_paths or ["/auth/register", "/auth/login", "/docs", "/redoc", "/openapi.json"]
        )
