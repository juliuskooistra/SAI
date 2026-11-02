from typing import List

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from ..database import get_db
from ..models.models import OrderRequest, OrderResponse
from ..services.order_service import OrderService


class OrderRouter:
    """
    Buying a bike: the customer reserves it here, then pays and collects it in the shop.
    Authentication, billing, and rate limiting are handled by middleware.
    """

    def __init__(self):
        self.router = APIRouter()
        self.order_service = OrderService()
        self._register_routes()

    def _register_routes(self):
        """
        Register the order routes. The function names are the operation_ids (SPEC §6, §8).
        """
        self.router.post("/orders", response_model=OrderResponse,
                         summary="Reserve a bike for sale")(self.reserve_bike)
        self.router.get("/orders", response_model=List[OrderResponse],
                        summary="Your orders")(self.list_my_orders)
        self.router.post("/orders/{order_id}/cancel", response_model=OrderResponse,
                         summary="Cancel one of your reservations")(self.cancel_my_order)

    def reserve_bike(self, request: OrderRequest, req: Request, db: Session = Depends(get_db)) -> OrderResponse:
        """
        Reserves a sale bike for the caller for 7 days; they pay and collect it
        in the shop. After 7 days the reservation expires and the bike is for
        sale again. Changes state: confirm with the customer first. Costs 5 API tokens.
        """
        order = self.order_service.reserve(db, req.state.user_id, request.bike_id)
        return OrderResponse(**self.order_service.describe(db, order))

    def list_my_orders(self, req: Request, db: Session = Depends(get_db)) -> List[OrderResponse]:
        """Use this to see the caller's reservations and purchases."""
        orders = self.order_service.list_orders(db, user_id=req.state.user_id)
        return [OrderResponse(**self.order_service.describe(db, o)) for o in orders]

    def cancel_my_order(self, order_id: int, req: Request, db: Session = Depends(get_db)) -> OrderResponse:
        """
        Cancels one of the caller's reservations; the bike is for sale again.
        Changes state: confirm with the customer first.
        """
        order = self.order_service.cancel(db, order_id, req.state.user_id)
        return OrderResponse(**self.order_service.describe(db, order))
