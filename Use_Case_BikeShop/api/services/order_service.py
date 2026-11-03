"""
Sales: a customer reserves a sale bike, pays and collects it in the shop
(SPEC §5.5), and the worker releases reservations that ran out (§5.7).
Each reservation and each expiry queues an email in the same transaction (§5.9).

Every state change is a conditional update ("... WHERE status = 'reserved'"),
so a customer, a staff member and the worker acting at the same moment
can't both win: the second one finds nothing to change.
"""
from datetime import timedelta
from typing import Optional

from sqlalchemy import update
from sqlmodel import Session, select

from ..config import ORDER_HOLD_DAYS, MAX_RESERVED_ORDERS_PER_CUSTOMER
from ..database import start_write_transaction
from ..models.models import Bike, BikeStatus, Order, OrderStatus, Purpose, User
from ..timeutils import utcnow, format_local
from .errors import Conflict, NotFound
from .notification_service import NotificationService


class OrderService:
    """
    Service class for sale orders.
    """

    def reserve(self, db: Session, user_id: str, bike_id: int) -> Order:
        """Reserve a sale bike for ORDER_HOLD_DAYS days."""
        start_write_transaction(db)
        try:
            bike = db.get(Bike, bike_id)
            if not bike or bike.status == BikeStatus.retired:
                raise NotFound(f"There is no bike with id {bike_id}.")
            if bike.purpose != Purpose.sale:
                raise Conflict(f"{bike.name} ({bike.code}) is a rental bike and isn't for sale.")
            if bike.status == BikeStatus.reserved:
                raise Conflict(f"{bike.name} ({bike.code}) is already reserved by another customer.")
            if bike.status == BikeStatus.sold:
                raise Conflict(f"{bike.name} ({bike.code}) has already been sold.")
            reserved = len(db.exec(select(Order.id).where(
                Order.user_id == user_id, Order.status == OrderStatus.reserved)).all())
            if reserved >= MAX_RESERVED_ORDERS_PER_CUSTOMER:
                raise Conflict(
                    f"You already have {reserved} reserved bikes; the limit is "
                    f"{MAX_RESERVED_ORDERS_PER_CUSTOMER}. Collect or cancel one first."
                )
            now = utcnow()
            order = Order(bike_id=bike.id, user_id=user_id, price_chf=bike.sale_price_chf,
                          status=OrderStatus.reserved, created_at=now,
                          expires_at=now + timedelta(days=ORDER_HOLD_DAYS))
            db.add(order)
            bike.status = BikeStatus.reserved
            bike.updated_at = now
            db.add(bike)
            db.flush()
            NotificationService().bike_reserved(db, order)
            db.commit()
            db.refresh(order)
            return order
        except Exception:
            db.rollback()
            raise

    def list_orders(self, db: Session, user_id: Optional[str] = None,
                    status: Optional[OrderStatus] = None) -> list[Order]:
        query = select(Order)
        if user_id:
            query = query.where(Order.user_id == user_id)
        if status:
            query = query.where(Order.status == status)
        return db.exec(query.order_by(Order.created_at.desc())).all()

    def get_order(self, db: Session, order_id: int, user_id: Optional[str] = None) -> Order:
        order = db.get(Order, order_id)
        if not order or (user_id and order.user_id != user_id):
            raise NotFound(f"There is no order with id {order_id} on your account.")
        return order

    def _close(self, db: Session, order: Order, new_status: OrderStatus, bike_status: BikeStatus) -> bool:
        """reserved -> new_status, and the bike reserved -> bike_status. True if this call did it."""
        now = utcnow()
        changed = db.execute(
            update(Order).where(Order.id == order.id, Order.status == OrderStatus.reserved)
            .values(status=new_status, closed_at=now)
        ).rowcount == 1
        if changed:
            db.execute(
                update(Bike).where(Bike.id == order.bike_id, Bike.status == BikeStatus.reserved)
                .values(status=bike_status, updated_at=now)
            )
        return changed

    def _finish(self, db: Session, order_id: int, user_id: Optional[str],
                new_status: OrderStatus, bike_status: BikeStatus) -> Order:
        start_write_transaction(db)
        try:
            order = self.get_order(db, order_id, user_id)
            if not self._close(db, order, new_status, bike_status):
                raise Conflict(f"This order is {order.status.value}; only reserved orders can be changed.")
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(order)
        return order

    def cancel(self, db: Session, order_id: int, user_id: Optional[str] = None) -> Order:
        """Owner (user_id given) or staff cancels; the bike is for sale again."""
        return self._finish(db, order_id, user_id, OrderStatus.cancelled, BikeStatus.available)

    def complete(self, db: Session, order_id: int) -> Order:
        """Staff: the customer paid and took the bike."""
        return self._finish(db, order_id, None, OrderStatus.completed, BikeStatus.sold)

    def expire_reservations(self, db: Session) -> int:
        """
        The scheduled job (SPEC §5.7), run by the worker: release every
        reservation past its expires_at and queue a "reservation expired"
        email for each. Safe to run twice; returns how many it expired.
        """
        start_write_transaction(db)
        try:
            now = utcnow()
            due = db.exec(select(Order).where(
                Order.status == OrderStatus.reserved, Order.expires_at <= now)).all()
            expired = 0
            for order in due:
                if self._close(db, order, OrderStatus.expired, BikeStatus.available):
                    NotificationService().reservation_expired(db, order)
                    expired += 1
            db.commit()
            return expired
        except Exception:
            db.rollback()
            raise

    def describe(self, db: Session, order: Order, with_username: bool = False) -> dict:
        """Order plus bike name/code, ready for OrderResponse."""
        bike = db.get(Bike, order.bike_id)
        data = order.model_dump()
        data.update(bike_code=bike.code, bike_name=bike.name)
        if with_username:
            user = db.exec(select(User).where(User.user_id == order.user_id)).first()
            data["username"] = user.username if user else None
        return data

    def hold_message(self, order: Order) -> str:
        return f"Held for you until {format_local(order.expires_at)}."
