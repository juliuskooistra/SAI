"""
Billing Middleware for FastAPI.

This middleware handles token consumption and billing for billable endpoints.
Requires AuthenticationMiddleware to be applied first.
"""

import time
from typing import Optional, Any
from fastapi import Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware
from sqlmodel import Session

from ..database import get_db
from ..models.models import APIUsage
from ..services.billing_service import BillingService


class BillingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that handles token consumption and billing for billable endpoints.
    Requires user authentication to be completed first.
    """

    def __init__(self, app, protected_paths: Optional[list] = None, excluded_paths: Optional[list] = None):
        """
        Initialize the billing middleware.
        
        :param app: FastAPI application instance
        :param protected_paths: List of path prefixes that require billing
        :param excluded_paths: List of specific paths to exclude from billing
        """
        super().__init__(app)
        self.billing_service = BillingService()
        
        # Default protected paths - only API endpoints are billable
        self.protected_paths = protected_paths or ["/api/"]
        
        # Exclude auth, billing, and docs from billing
        self.excluded_paths = excluded_paths or [
            "/auth/", "/billing/",  # Don't bill auth/billing operations
            "/docs", "/redoc", "/openapi.json",  # Documentation
            "/favicon.ico", "/health", "/status"  # Health checks
        ]

    def _requires_billing(self, path: str) -> bool:
        """Check if an endpoint requires billing."""
        # Check specific exclusions first
        for excluded in self.excluded_paths:
            if path.startswith(excluded):
                return False
        
        # Check if path matches protected patterns
        for protected in self.protected_paths:
            if path.startswith(protected):
                return True
                
        return False

    def _calculate_endpoint_cost(self, path: str, method: str, request_body: Any = None) -> float:
        """Calculate token cost for an endpoint."""
        # Map paths to costs
        cost_map = {
            "/api/peak-voltages": 1.0,
        }
        
        base_cost = cost_map.get(path, 1.0)
        
        # For batch requests, multiply by number of items
        if path == "/api/peak-voltages" and request_body and isinstance(request_body, dict):
            if "data" in request_body and isinstance(request_body["data"], list):
                return base_cost * len(request_body["data"])
                
        return base_cost

    async def dispatch(self, request: Request, call_next):
        """Main billing middleware logic."""
        start_time = time.time()
        path = request.url.path
        method = request.method
        
        # Skip non-billable endpoints
        if not self._requires_billing(path):
            response = await call_next(request)
            return response

        # Check if user is authenticated (should be set by AuthenticationMiddleware)
        if not hasattr(request.state, 'user_id') or not request.state.user_id:
            return Response(
                content='{"detail":"Authentication required for billing"}',
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"Content-Type": "application/json"}
            )

        # Get database session
        db_generator = get_db()
        db = next(db_generator)
        
        try:
            user_id = request.state.user_id
            api_key_id = getattr(request.state, 'api_key_id', None)

            # Get request body for cost calculation
            request_body = None
            if method in ["POST", "PUT", "PATCH"]:
                try:
                    body_bytes = await request.body()
                    if body_bytes:
                        import json
                        request_body = json.loads(body_bytes.decode())
                        
                        # Recreate request with body (since it was consumed)
                        async def receive():
                            return {"type": "http.request", "body": body_bytes}
                        request._receive = receive
                except:
                    pass  # Continue without request body if parsing fails

            # Calculate token cost
            token_cost = self._calculate_endpoint_cost(path, method, request_body)

            # Check sufficient balance
            if not self.billing_service.check_sufficient_balance(user_id, token_cost, db):
                current_balance = self.billing_service.get_user_balance(user_id, db)
                return Response(
                    content=f'{{"detail":"Insufficient token balance. Required: {token_cost}, Available: {current_balance}"}}',
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    headers={"Content-Type": "application/json"}
                )

            # Add billing context to request state
            request.state.token_cost = token_cost

            # Process the actual request
            try:
                response = await call_next(request)
                processing_time = (time.time() - start_time) * 1000  # Convert to milliseconds
                
                # Only consume tokens and log usage for successful requests
                if 200 <= response.status_code < 300:
                    # Consume tokens
                    success = self.billing_service.consume_tokens(
                        user_id=user_id,
                        api_key_id=api_key_id,
                        endpoint=path,
                        tokens_consumed=token_cost,
                        request_data=request_body or {},
                        db=db
                    )
                    
                    if success:
                        # Add billing headers to response
                        new_balance = self.billing_service.get_user_balance(user_id, db)
                        response.headers["X-Tokens-Consumed"] = str(token_cost)
                        response.headers["X-Remaining-Balance"] = str(new_balance)
                        response.headers["X-Processing-Time-Ms"] = str(round(processing_time, 2))
                    
                    # Log successful usage
                    self._log_usage(
                        user_id=user_id,
                        api_key_id=api_key_id,
                        endpoint=path,
                        tokens_consumed=token_cost if success else 0,
                        request_body=request_body,
                        response_status=response.status_code,
                        processing_time=processing_time,
                        success=True,
                        db=db
                    )
                else:
                    # Log failed usage (don't consume tokens)
                    self._log_usage(
                        user_id=user_id,
                        api_key_id=api_key_id,
                        endpoint=path,
                        tokens_consumed=0,
                        request_body=request_body,
                        response_status=response.status_code,
                        processing_time=processing_time,
                        success=False,
                        error_message=f"HTTP {response.status_code}",
                        db=db
                    )
                
                return response
                
            except Exception as e:
                processing_time = (time.time() - start_time) * 1000
                
                # Log failed request (don't consume tokens)
                self._log_usage(
                    user_id=user_id,
                    api_key_id=api_key_id,
                    endpoint=path,
                    tokens_consumed=0,
                    request_body=request_body,
                    response_status=500,
                    processing_time=processing_time,
                    success=False,
                    error_message=str(e),
                    db=db
                )
                
                # Re-raise the exception
                raise e
                
        except Exception as e:
            # Handle any billing-level exceptions
            return Response(
                content=f'{{"detail":"Billing error: {str(e)}"}}',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                headers={"Content-Type": "application/json"}
            )
        finally:
            # Close database session
            db.close()

    def _log_usage(self, user_id: str, api_key_id: Optional[int], endpoint: str, 
                   tokens_consumed: float, request_body: Any, response_status: int,
                   processing_time: float, success: bool, error_message: str = None, db: Session = None):
        """Log API usage for analytics."""
        if not db:
            return
            
        try:
            usage = APIUsage(
                user_id=user_id,
                api_key_id=api_key_id,
                endpoint=endpoint,
                tokens_consumed=tokens_consumed,
                request_size=len(str(request_body)) if request_body else 0,
                response_size=0,  # Will be updated if needed
                processing_time_ms=processing_time,
                success=success,
                error_message=error_message
            )
            db.add(usage)
            db.commit()
        except Exception as e:
            # Don't let logging errors break the request
            print(f"Failed to log usage: {e}")
            db.rollback()


class BillingConfig:
    """Configuration helper for billing middleware."""
    
    @staticmethod
    def create_middleware(protected_paths: list = None, excluded_paths: list = None):
        """Create a configured billing middleware instance."""
        return BillingMiddleware(
            app=None,  # Will be set by FastAPI
            protected_paths=protected_paths or ["/api/"],
            excluded_paths=excluded_paths or ["/auth/", "/billing/"]
        )
