from fastapi import APIRouter, Request
import pandas as pd

from ..models.models import PeakVoltageListRequest, PeakVoltageListResponse, PeakVoltageResponse
from ..services.peak_voltage_service import PeakVoltageService

class PeakVoltageRouter:
    def __init__(self):
        self.router = APIRouter()
        self.peak_voltage_service = PeakVoltageService()
        self._register_routes()

    def _register_routes(self):
        """
        Register the peak voltage prediction routes.
        Authentication, billing, and rate limiting are handled by middleware.
        """
        self.router.post("/peak-voltages", response_model=PeakVoltageListResponse)(self.get_peak_voltages)

    def get_peak_voltages(self, request: PeakVoltageListRequest, req: Request):
        """
        Get peak voltages data.
        
        Authentication, billing, and rate limiting are automatically handled by the 
        BillingRateLimitMiddleware before this endpoint is reached.
        
        The middleware adds user context to request.state:
        - req.state.user_id: ID of the authenticated user
        - req.state.api_key_id: ID of the API key used
        - req.state.token_cost: Number of tokens that will be consumed
        """
        # At this point, the middleware has already:
        # 1. Authenticated the user via API key
        # 2. Checked rate limits
        # 3. Verified sufficient token balance
        # 4. Added user context to request.state
        
        # The middleware will consume tokens and log usage after successful response
        peak_voltage_data = pd.DataFrame([data.model_dump() for data in request.data])

        peak_voltage_results = self.peak_voltage_service.get_peak_voltages(peak_voltage_data, request.return_scaled)

        return PeakVoltageListResponse(
            data=[
                PeakVoltageResponse(**data.model_dump(), U_max=prediction)
                for data, prediction in zip(request.data, peak_voltage_results)
            ]
        )