from router.peak_voltage_router import PeakVoltageRouter
from router.auth_router import AuthRouter
from router.billing_router import BillingRouter

from middleware.auth_middleware import AuthenticationMiddleware
from middleware.rate_limit_middleware import RateLimitMiddleware
from middleware.billing_middleware import BillingMiddleware

from database import init_database
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from scalar_fastapi import get_scalar_api_reference

class PeakVoltageAPI:
    """
    Peak Voltage API for handling peak voltage predictions.
    """

    def __init__(self):
        """
        Initialize the PeakVoltageAPI with FastAPI and register the router.
        """
        # Initialize database
        init_database()
        
        self.app = FastAPI(title="Peak Voltage API", docs_url=None, redoc_url=None, version="1.0.0")
        self._configure_middleware()
        self._register_routes()


    def _configure_middleware(self):
        """
        Configure middleware for the FastAPI application.
        
        Middleware is applied in reverse order (last added is executed first).
        Order of execution: Billing -> Rate Limiting -> Authentication -> CORS
        """
        # Add middleware in reverse order of execution
        
        # 1. Billing middleware (applied last, executed first for billable endpoints)
        self.app.add_middleware(
            BillingMiddleware,
            protected_paths=["/api/"],  # Only API endpoints are billable
            excluded_paths=["/auth/", "/billing/", "/docs", "/redoc", "/openapi.json"]
        )
        
        # 2. Rate limiting middleware (applied before billing)
        self.app.add_middleware(
            RateLimitMiddleware,
            protected_paths=["/api/"],  # Only API endpoints are rate limited
            excluded_paths=["/auth/", "/billing/", "/docs", "/redoc", "/openapi.json"]
        )
        
        # 3. Authentication middleware (applied before rate limiting and billing)
        self.app.add_middleware(
            AuthenticationMiddleware,
            protected_paths=["/api/", "/billing/"],  # API and billing endpoints need auth
            excluded_paths=["/auth/register", "/auth/login", "/docs", "/redoc", "/openapi.json"]
        )

        # 4. CORS middleware (applied before anything else)
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # Allow all origins
            allow_credentials=True,
            allow_methods=["*"],  # Allow all methods
            allow_headers=["*"],  # Allow all headers
        )

    def _register_routes(self):
        """
        Register the API routes for peak voltage predictions, authentication, and billing.
        """
        # Register routes
        # Create auth router (for user registration and API key management)
        self.app.include_router(AuthRouter().router, prefix="/auth", tags=["authentication"])
        # Create billing router (authentication handled by middleware)
        self.app.include_router(BillingRouter().router, prefix="/billing", tags=["billing"])
        # Create peak voltage router (authentication and billing handled by middleware)
        self.app.include_router(PeakVoltageRouter().router, prefix="/api", tags=["peak_voltage"])
        
        # Add a custom docs route
        self.app.add_api_route("/docs", self.get_docs, include_in_schema=False)

    def get_docs(self):
        """
        Custom documentation route for the API.
        """
        return get_scalar_api_reference(
            openapi_url=self.app.openapi_url,
            title=self.app.title
        )


    def run(self, host: str = "0.0.0.0", port: int = 8000):
        """
        Run the FastAPI application.

        :param host: Host address to run the application on.
        :param port: Port number to run the application on.
        """
        uvicorn.run(self.app, host=host, port=port)

    
if __name__ == "__main__":
    """
    Entry point to run the Peak Voltage API.
    """
    api = PeakVoltageAPI()
    api.run()