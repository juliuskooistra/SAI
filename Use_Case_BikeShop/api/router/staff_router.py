from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from ..database import get_db
from ..models.models import (
    BikeCreateRequest, BikeResponse, BikeUpdateRequest, Category, InventoryCount, InventorySummary,
    OrderResponse, OrderStatus, RentalRateRequest, RentalRateResponse, RentalResponse, RentalStatus,
)
from ..services import analytics_service
from ..services.analytics_service import AnalyticsSummary
from ..services.inventory_service import InventoryService
from ..services.order_service import OrderService
from ..services.rental_service import RentalService


class StaffRouter:
    """
    Shop staff: inventory, prices, pick-ups and returns, sales.
    The AuthenticationMiddleware lets only staff keys through to /staff/*
    (403 otherwise). Staff calls are not rate limited or billed.
    """

    def __init__(self):
        self.router = APIRouter()
        self.inventory_service = InventoryService()
        self.rental_service = RentalService()
        self.order_service = OrderService()
        self._register_routes()

    def _register_routes(self):
        """
        Register the staff routes. The function names are the operation_ids (SPEC §6, §8).
        """
        r = self.router
        r.get("/bikes", response_model=List[BikeResponse], summary="Every bike, retired and sold included")(self.list_all_bikes)
        r.post("/bikes", response_model=BikeResponse, summary="Add a bike")(self.create_bike)
        r.patch("/bikes/{bike_id}", response_model=BikeResponse, summary="Edit a bike")(self.update_bike)
        r.post("/bikes/{bike_id}/retire", response_model=BikeResponse, summary="Retire a bike")(self.retire_bike)
        r.get("/inventory", response_model=InventorySummary, summary="Stock counts and what needs attention")(self.inventory_summary)
        r.put("/rental-rates/{category}", response_model=RentalRateResponse, summary="Set a rental price")(self.set_rental_rate)
        r.get("/rentals", response_model=List[RentalResponse], summary="All rentals, filtered")(self.list_rentals)
        r.post("/rentals/{rental_id}/pickup", response_model=RentalResponse, summary="Hand a bike over")(self.pickup_rental)
        r.post("/rentals/{rental_id}/return", response_model=RentalResponse, summary="Take a bike back")(self.return_rental)
        r.post("/rentals/{rental_id}/cancel", response_model=RentalResponse, summary="Cancel a booking")(self.staff_cancel_rental)
        r.get("/orders", response_model=List[OrderResponse], summary="All orders")(self.list_orders)
        r.post("/orders/{order_id}/complete", response_model=OrderResponse, summary="Customer paid and took the bike")(self.complete_order)
        r.post("/orders/{order_id}/cancel", response_model=OrderResponse, summary="Cancel a reservation")(self.staff_cancel_order)
        r.get("/analytics", response_model=AnalyticsSummary, summary="Anonymous product analytics")(self.analytics_summary)

    # ------------------------------------------------------------ bikes

    def list_all_bikes(self, db: Session = Depends(get_db)) -> List[BikeResponse]:
        """Every bike in the system, including retired and sold ones."""
        return [BikeResponse.model_validate(b) for b in self.inventory_service.all_bikes(db)]

    def create_bike(self, request: BikeCreateRequest, db: Session = Depends(get_db)) -> BikeResponse:
        """Adds a bike. Sale bikes need sale_price_chf; rental bikes must not have one."""
        return BikeResponse.model_validate(self.inventory_service.create_bike(db, request))

    def update_bike(self, bike_id: int, request: BikeUpdateRequest, db: Session = Depends(get_db)) -> BikeResponse:
        """
        Changes the given fields. Status: only rental bikes, only between
        'available' and 'maintenance'. Bookings on a bike in maintenance stay,
        and show up as at risk.
        """
        return BikeResponse.model_validate(self.inventory_service.update_bike(db, bike_id, request))

    def retire_bike(self, bike_id: int, db: Session = Depends(get_db)) -> BikeResponse:
        """Takes a bike out of the catalogue. Not allowed while it has open rentals or a reservation."""
        return BikeResponse.model_validate(self.inventory_service.retire_bike(db, bike_id))

    def inventory_summary(self, db: Session = Depends(get_db)) -> InventorySummary:
        """Counts by purpose, category and status; bikes out now; overdue; at-risk bookings; reservations about to expire."""
        data = self.inventory_service.summary(db)
        return InventorySummary(
            counts=[InventoryCount(**c) for c in data["counts"]],
            rental_bikes_out_now=data["rental_bikes_out_now"],
            overdue_rentals=[RentalResponse(**self.rental_service.describe(db, r, True)) for r in data["overdue"]],
            at_risk_bookings=[RentalResponse(**self.rental_service.describe(db, r, True)) for r in data["at_risk"]],
            orders_expiring_within_24h=[OrderResponse(**self.order_service.describe(db, o, True)) for o in data["expiring"]],
        )

    # ------------------------------------------------------------ prices

    def set_rental_rate(self, category: Category, request: RentalRateRequest,
                        db: Session = Depends(get_db)) -> RentalRateResponse:
        """Sets the price for a category. Existing bookings keep their price."""
        return RentalRateResponse.model_validate(self.inventory_service.set_rate(db, category, request))

    # ------------------------------------------------------------ rentals

    def list_rentals(self, status: Optional[RentalStatus] = None, date: Optional[date] = None,
                     bike_id: Optional[int] = None, user_id: Optional[str] = None,
                     overdue: Optional[bool] = None, db: Session = Depends(get_db)) -> List[RentalResponse]:
        """All rentals. date = a day (Zurich) the rental starts or ends on: the day's pick-ups and returns."""
        rentals = self.rental_service.list_rentals(db, user_id=user_id, status=status, on_date=date,
                                                   bike_id=bike_id, overdue=overdue)
        return [RentalResponse(**self.rental_service.describe(db, r, True)) for r in rentals]

    def pickup_rental(self, rental_id: int, db: Session = Depends(get_db)) -> RentalResponse:
        """Hands the bike over: booked -> active. Only on the rental's start date."""
        rental = self.rental_service.pickup(db, rental_id)
        return RentalResponse(**self.rental_service.describe(db, rental, True))

    def return_rental(self, rental_id: int, db: Session = Depends(get_db)) -> RentalResponse:
        """Takes the bike back: active -> returned. The response carries the final price."""
        rental = self.rental_service.return_bike(db, rental_id)
        return RentalResponse(**self.rental_service.describe(db, rental, True))

    def staff_cancel_rental(self, rental_id: int, db: Session = Depends(get_db)) -> RentalResponse:
        """Cancels any booked rental."""
        rental = self.rental_service.cancel(db, rental_id)
        return RentalResponse(**self.rental_service.describe(db, rental, True))

    # ------------------------------------------------------------ orders

    def list_orders(self, status: Optional[OrderStatus] = None, db: Session = Depends(get_db)) -> List[OrderResponse]:
        """All orders, newest first."""
        return [OrderResponse(**self.order_service.describe(db, o, True))
                for o in self.order_service.list_orders(db, status=status)]

    def complete_order(self, order_id: int, db: Session = Depends(get_db)) -> OrderResponse:
        """The customer paid and took the bike: order completed, bike sold."""
        order = self.order_service.complete(db, order_id)
        return OrderResponse(**self.order_service.describe(db, order, True))

    def staff_cancel_order(self, order_id: int, db: Session = Depends(get_db)) -> OrderResponse:
        """Cancels a reservation; the bike is for sale again."""
        order = self.order_service.cancel(db, order_id)
        return OrderResponse(**self.order_service.describe(db, order, True))

    # ------------------------------------------------------------ analytics

    def analytics_summary(self, days: int = Query(30, ge=1, le=365, description="Period in days, today included"),
                          db: Session = Depends(get_db)) -> AnalyticsSummary:
        """
        Anonymous product analytics (SPEC §5.10): counts per day and event, the
        10 most-viewed bikes, and how many quotes became bookings. Days are
        Zurich dates. No user ids are stored, so none are shown.
        """
        return analytics_service.summary(db, days)
