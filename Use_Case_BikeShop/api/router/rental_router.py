from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session

from ..database import get_db
from ..models.models import (
    AvailabilityResponse, AvailableBike, BikeResponse, Category, FrameSize, QuoteResponse,
    RentalPeriodRequest, RentalResponse, RentalStatus,
)
from ..services import analytics_service
from ..services.rental_service import RentalService
from ..timeutils import to_utc


def quote_response(bike, rate, price, start, end) -> QuoteResponse:
    return QuoteResponse(
        bike_id=bike.id, category=bike.category, start_at=start, end_at=end,
        hours=price.hours, full_days=price.full_days, rest_hours=price.rest_hours,
        hourly_chf=rate.hourly_chf, daily_chf=rate.daily_chf, total_chf=price.total_chf,
        deposit_chf=rate.deposit_chf,
    )


class RentalRouter:
    """
    Availability, quotes and the customer's own bookings.
    Authentication, billing, and rate limiting are handled by middleware;
    the middleware puts the caller in req.state.user_id.
    """

    def __init__(self):
        self.router = APIRouter()
        self.rental_service = RentalService()
        self._register_routes()

    def _register_routes(self):
        """
        Register the rental routes. The function names are the operation_ids (SPEC §6, §8).
        """
        self.router.get("/availability", response_model=AvailabilityResponse,
                        summary="Rental bikes free for a period, with prices")(self.check_availability)
        self.router.post("/rentals/quote", response_model=QuoteResponse,
                         summary="Price for renting one bike; books nothing")(self.quote_rental)
        self.router.post("/rentals", response_model=RentalResponse,
                         summary="Book a rental bike")(self.book_rental)
        self.router.get("/rentals", response_model=List[RentalResponse],
                        summary="Your rentals")(self.list_my_rentals)
        self.router.get("/rentals/{rental_id}", response_model=RentalResponse,
                        summary="One of your rentals")(self.get_my_rental)
        self.router.post("/rentals/{rental_id}/cancel", response_model=RentalResponse,
                         summary="Cancel one of your booked rentals")(self.cancel_my_rental)

    def check_availability(self,
                           start_at: datetime = Query(..., description="Pick-up time, ISO 8601 (no offset = Zurich time)",
                                                      examples=["2026-11-07T10:00"]),
                           end_at: datetime = Query(..., description="Return time, ISO 8601 (no offset = Zurich time)",
                                                    examples=["2026-11-07T15:00"]),
                           category: Optional[Category] = None,
                           frame_size: Optional[FrameSize] = None,
                           db: Session = Depends(get_db)) -> AvailabilityResponse:
        """
        Use this to find which rental bikes are free for a period. No side
        effects. Each bike comes with its price for exactly that period.
        """
        start, end = to_utc(start_at), to_utc(end_at)
        found = self.rental_service.available_bikes(db, start, end, category, frame_size)
        return AvailabilityResponse(
            start_at=start, end_at=end,
            bikes=[AvailableBike(bike=BikeResponse.model_validate(bike),
                                 quote=quote_response(bike, rate, price, start, end))
                   for bike, rate, price in found],
        )

    def quote_rental(self, request: RentalPeriodRequest, db: Session = Depends(get_db)) -> QuoteResponse:
        """
        Use this to tell a customer what a rental would cost. No side effects,
        and it does not check whether the bike is free (use check_availability).
        """
        start, end = to_utc(request.start_at), to_utc(request.end_at)
        bike, rate, price = self.rental_service.quote(db, request.bike_id, start, end)
        result = quote_response(bike, rate, price, start, end)
        analytics_service.record(db, "quote", bike.id)   # anonymous, never fails the request (SPEC §5.10)
        return result

    def book_rental(self, request: RentalPeriodRequest, req: Request, db: Session = Depends(get_db)) -> RentalResponse:
        """
        Books the bike for the caller. Changes state: confirm with the customer
        first. Fails with 409 if the bike is taken or the customer already has
        3 open rentals, with 400 if a shop rule is broken. Costs 5 API tokens.
        """
        rental = self.rental_service.book(db, req.state.user_id, request.bike_id,
                                          to_utc(request.start_at), to_utc(request.end_at))
        result = RentalResponse(**self.rental_service.describe(db, rental))
        analytics_service.record(db, "booking", result.bike_id)
        return result

    def list_my_rentals(self, req: Request, status: Optional[RentalStatus] = None,
                        db: Session = Depends(get_db)) -> List[RentalResponse]:
        """Use this to see the caller's rentals, optionally filtered by status."""
        rentals = self.rental_service.list_rentals(db, user_id=req.state.user_id, status=status)
        return [RentalResponse(**self.rental_service.describe(db, r)) for r in rentals]

    def get_my_rental(self, rental_id: int, req: Request, db: Session = Depends(get_db)) -> RentalResponse:
        """One of the caller's rentals; other people's rentals answer 404."""
        rental = self.rental_service.get_rental(db, rental_id, req.state.user_id)
        return RentalResponse(**self.rental_service.describe(db, rental))

    def cancel_my_rental(self, rental_id: int, req: Request, db: Session = Depends(get_db)) -> RentalResponse:
        """
        Cancels one of the caller's booked rentals, free of charge, as long as
        it hasn't started. Changes state: confirm with the customer first.
        """
        rental = self.rental_service.cancel(db, rental_id, req.state.user_id)
        return RentalResponse(**self.rental_service.describe(db, rental))
