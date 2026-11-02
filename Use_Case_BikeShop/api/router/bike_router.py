from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from ..database import get_db
from ..models.models import (
    BikeDetailResponse, BikeResponse, Category, Condition, FrameSize, OpeningHoursResponse, Purpose,
    RentalRate, RentalRateResponse,
)
from ..services.inventory_service import InventoryService


class BikeRouter:
    """
    Catalogue and price list for customers (≙ PeakVoltageRouter in VoltagePredictor).
    Authentication, billing, and rate limiting are handled by middleware.
    """

    def __init__(self):
        self.router = APIRouter()
        self.inventory_service = InventoryService()
        self._register_routes()

    def _register_routes(self):
        """
        Register the catalogue routes. The function names are the operation_ids (SPEC §6, §8).
        """
        self.router.get("/bikes", response_model=List[BikeResponse],
                        summary="Search bikes for sale and for rent")(self.search_bikes)
        self.router.get("/bikes/{bike_id}", response_model=BikeDetailResponse,
                        summary="Get one bike, with its rental price if it is a rental bike")(self.get_bike)
        self.router.get("/rental-rates", response_model=List[RentalRateResponse],
                        summary="The rental price list per bike category")(self.list_rental_rates)
        self.router.get("/opening-hours", response_model=OpeningHoursResponse,
                        summary="Opening hours, closed days and booking rules")(self.get_opening_hours)

    def search_bikes(self,
                     purpose: Optional[Purpose] = Query(None, description="'rental' or 'sale'"),
                     category: Optional[Category] = None,
                     frame_size: Optional[FrameSize] = None,
                     max_price_chf: Optional[Decimal] = Query(None, gt=0, description="Sale bikes up to this price"),
                     condition: Optional[Condition] = None,
                     q: Optional[str] = Query(None, description="Text in name, brand or description"),
                     db: Session = Depends(get_db)) -> List[BikeResponse]:
        """
        Use this to find bikes. Combine filters freely. Setting max_price_chf
        returns sale bikes only. Retired and sold bikes never appear.
        For rentals at a given time, use check_availability instead.
        """
        bikes = self.inventory_service.search_bikes(db, purpose, category, frame_size, max_price_chf, condition, q)
        return [BikeResponse.model_validate(b) for b in bikes]

    def get_bike(self, bike_id: int, db: Session = Depends(get_db)) -> BikeDetailResponse:
        """
        Use this for the details of one bike. Rental bikes include their
        hourly and daily rates and the deposit.
        """
        bike = self.inventory_service.get_bike(db, bike_id)
        rate = db.get(RentalRate, bike.category) if bike.purpose == Purpose.rental else None
        return BikeDetailResponse(
            **BikeResponse.model_validate(bike).model_dump(),
            rental_rate=RentalRateResponse.model_validate(rate) if rate else None,
        )

    def list_rental_rates(self, db: Session = Depends(get_db)) -> List[RentalRateResponse]:
        """
        Use this to answer "how much does it cost to rent a ... bike".
        Price = every started hour at the hourly rate, capped at the daily rate per 24 hours.
        """
        return [RentalRateResponse.model_validate(r) for r in self.inventory_service.list_rates(db)]

    def get_opening_hours(self) -> OpeningHoursResponse:
        """
        Use this before suggesting rental times: pick-up and return must be
        within opening hours, on the quarter hour.
        """
        return OpeningHoursResponse(**self.inventory_service.opening_hours())
