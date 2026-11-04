"""
Email notifications (SPEC §5.9): builds the three emails and enqueues one
`send_email` job each. Nothing is sent here: the worker does that.

Each method runs inside the caller's write transaction and doesn't commit,
so the email is queued together with the change that causes it, or not at
all (SPEC §5.8).
"""
import html
import logging
from typing import Optional

from sqlmodel import Session, select

from .. import config
from ..jobqueue import queue
from ..models.models import Bike, Order, Rental, RentalRate, User
from ..timeutils import format_local
from .pricing_service import deposit

log = logging.getLogger("bikeshop.notifications")


def _compose(greeting: str, lines: list[str], link_text: str) -> tuple[str, str]:
    """Plain text and a simple HTML version of the same message."""
    link = f"{config.PUBLIC_URL.rstrip('/')}/#/my"
    text = "\n".join([greeting, "", *lines, "", f"{link_text}: {link}", "", "BikeShop"])
    body = "".join(f"<p>{html.escape(line)}</p>" for line in lines)
    page = (f"<p>{html.escape(greeting)}</p>{body}"
            f'<p><a href="{html.escape(link)}">{html.escape(link_text)}</a></p><p>BikeShop</p>')
    return text, page


class NotificationService:

    def _enqueue(self, db: Session, user_id: str, subject: str, lines: list[str], link_text: str) -> Optional[int]:
        user = db.exec(select(User).where(User.user_id == user_id)).first()
        if user is None or not user.email:
            log.warning("no email address for a notification; skipped", extra={"subject": subject})
            return None
        text, page = _compose(f"Hello {user.username},", lines, link_text)
        job = queue.enqueue(db, "send_email", {"to": user.email, "subject": subject, "text": text, "html": page},
                            user_id=user_id)
        return job.id

    def booking_confirmed(self, db: Session, rental: Rental) -> Optional[int]:
        bike = db.get(Bike, rental.bike_id)
        rate = db.get(RentalRate, bike.category)
        amount = deposit(rental.quoted_price_chf, rate.deposit_chf) if rate else 2 * rental.quoted_price_chf
        return self._enqueue(
            db, rental.user_id, f"Booking confirmed: {bike.name} on {format_local(rental.start_at)}",
            [f"Your booking of {bike.name} ({bike.code}) is confirmed.",
             f"Pick-up: {format_local(rental.start_at)}",
             f"Return: {format_local(rental.end_at)}",
             f"Price: CHF {rental.quoted_price_chf:.2f}, paid in the shop. "
             f"The deposit, CHF {amount:.2f}, is taken and returned at the counter."],
            "See your bookings")

    def bike_reserved(self, db: Session, order: Order) -> Optional[int]:
        bike = db.get(Bike, order.bike_id)
        return self._enqueue(
            db, order.user_id, f"Reserved: {bike.name}, held until {format_local(order.expires_at)}",
            [f"We have reserved {bike.name} ({bike.code}) for you.",
             f"Price: CHF {order.price_chf:.2f}, paid when you collect it in the shop.",
             f"We hold it until {format_local(order.expires_at)}. After that it is for sale again."],
            "See your orders")

    def reservation_expired(self, db: Session, order: Order) -> Optional[int]:
        bike = db.get(Bike, order.bike_id)
        return self._enqueue(
            db, order.user_id, f"Reservation expired: {bike.name}",
            [f"Your reservation of {bike.name} ({bike.code}) ran out on {format_local(order.expires_at)}, "
             f"so the bike is for sale again.",
             "If you still want it and it is available, you can reserve it again."],
            "See your orders")
