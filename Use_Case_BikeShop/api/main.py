from .router.bike_router import BikeRouter
from .router.rental_router import RentalRouter
from .router.order_router import OrderRouter
from .router.staff_router import StaffRouter
from .router.auth_router import AuthRouter
from .router.billing_router import BillingRouter

from .middleware.auth_middleware import AuthenticationMiddleware
from .middleware.rate_limit_middleware import RateLimitMiddleware
from .middleware.billing_middleware import BillingMiddleware

from .config import CORS_ORIGINS
from .database import init_database, check_database, get_db
from .models.models import HealthResponse, JobRun, JobStatus
from .services.errors import ShopError
from .services.inference_service import InferenceService

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import Session
import uvicorn
from scalar_fastapi import get_scalar_api_reference

DOCS_PATHS = ["/docs", "/redoc", "/openapi.json", "/health"]


class BikeShopAPI:
    """
    BikeShop API: a bike shop that sells bikes and rents them out.
    Same structure as PeakVoltageAPI in Use_Case_III/VoltagePredictor.
    """

    def __init__(self):
        """
        Initialize the BikeShopAPI with FastAPI and register the routers.
        """
        # Initialize database
        init_database()
        self.inference_service = InferenceService()

        self.app = FastAPI(
            title="BikeShop API",
            description="Buy and rent bikes. Customers use /api, staff use /staff. "
                        "Send your API key as 'Authorization: Bearer <key>'.",
            docs_url=None, redoc_url=None, version="1.0.0",
            # The function name of each endpoint is its operation_id (SPEC §8: stable tool names)
            generate_unique_id_function=lambda route: route.name,
        )
        self._configure_middleware()
        self._register_error_handlers()
        self._register_routes()

    def _configure_middleware(self):
        """
        Configure middleware for the FastAPI application.

        Middleware is applied in reverse order (last added is executed first).
        Order of execution: CORS -> Authentication -> Rate Limiting -> Billing -> endpoint
        """
        # 1. Billing middleware (added first, runs last: only for billable endpoints)
        self.app.add_middleware(
            BillingMiddleware,
            protected_paths=["/api/"],  # Only customer API endpoints are billable
            excluded_paths=["/auth/", "/billing/", "/staff/"] + DOCS_PATHS
        )

        # 2. Rate limiting middleware
        self.app.add_middleware(
            RateLimitMiddleware,
            protected_paths=["/api/"],  # Only customer API endpoints are rate limited
            excluded_paths=["/auth/", "/billing/", "/staff/"] + DOCS_PATHS
        )

        # 3. Authentication middleware (also checks the staff role)
        self.app.add_middleware(
            AuthenticationMiddleware,
            protected_paths=["/api/", "/billing/", "/staff/", "/auth/my-keys", "/auth/revoke-key"],
            excluded_paths=["/auth/register", "/auth/login", "/auth/generate-key"] + DOCS_PATHS,
            staff_paths=["/staff/"]
        )

        # 4. CORS middleware (added last, runs first). Origins come from .env.
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=CORS_ORIGINS,
            allow_credentials=False,  # API keys travel in a header, not in cookies
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _register_error_handlers(self):
        """
        Services raise ShopError subclasses and know nothing about HTTP (SPEC §8.3).
        Here they become {"detail": "..."} with the right status code.
        """
        @self.app.exception_handler(ShopError)
        async def _shop_error(_: Request, exc: ShopError):
            return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    def _register_routes(self):
        """
        Register the API routes.
        """
        # Public: registration, login, API keys
        self.app.include_router(AuthRouter().router, prefix="/auth", tags=["authentication"])
        # Account: tokens and usage (authentication handled by middleware)
        self.app.include_router(BillingRouter().router, prefix="/billing", tags=["billing"])
        # Customers (authentication, rate limiting and billing handled by middleware)
        self.app.include_router(BikeRouter().router, prefix="/api", tags=["catalogue"])
        self.app.include_router(RentalRouter().router, prefix="/api", tags=["rentals"])
        self.app.include_router(OrderRouter().router, prefix="/api", tags=["orders"])
        # Staff (authentication and the staff role checked by middleware)
        self.app.include_router(StaffRouter().router, prefix="/staff", tags=["staff"])

        self.app.add_api_route("/health", self.health, methods=["GET"], response_model=HealthResponse,
                               tags=["health"], summary="Is the API up, and can it reach its dependencies?")
        # Add a custom docs route
        self.app.add_api_route("/docs", self._get_docs, include_in_schema=False)

    def health(self) -> HealthResponse:
        """
        Public. Always 200 while the API runs: a down LLM endpoint must not make
        the shop look dead (SPEC §8.1). Shows the scheduler's last run (§5.7).
        """
        db: Session = next(get_db())
        try:
            job = db.get(JobRun, "expire-reservations")
            scheduler = JobStatus.model_validate(job) if job else JobStatus()
        except Exception:  # noqa: BLE001 - health check reports, never raises
            scheduler = JobStatus()
        finally:
            db.close()
        return HealthResponse(
            database=check_database(),
            inference=self.inference_service.check(),
            scheduler=scheduler,
        )

    def _get_docs(self):
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


# This is merely here for testing purposes. In the real deployment, use uvicorn command line.
if __name__ == "__main__":
    """
    Entry point to run the BikeShop API.
    """
    api = BikeShopAPI()
    api.run()
