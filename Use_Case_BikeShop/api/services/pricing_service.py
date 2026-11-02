"""
Rental pricing (SPEC §5.3). Pure functions: no database, no clock.

    hours = ceil(duration in hours)          # every started hour counts
    days, rest = divmod(hours, 24)
    price = days x daily + min(rest x hourly, daily)
"""
import math
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from ..config import MONEY_PLACES, MIN_RENTAL_HOURS
from .errors import InvalidInput


@dataclass(frozen=True)
class PriceBreakdown:
    hours: int
    full_days: int
    rest_hours: int
    total_chf: Decimal


def money(value: Decimal) -> Decimal:
    """Round to centimes."""
    return Decimal(value).quantize(MONEY_PLACES, rounding=ROUND_HALF_UP)


def billable_hours(start: datetime, end: datetime) -> int:
    """Started hours between start and end, at least MIN_RENTAL_HOURS."""
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        raise InvalidInput("The return time must be after the pick-up time.")
    return max(MIN_RENTAL_HOURS, math.ceil(seconds / 3600))


def rental_price(start: datetime, end: datetime, hourly_chf: Decimal, daily_chf: Decimal) -> PriceBreakdown:
    """Price of renting from start to end at the given rates."""
    hours = billable_hours(start, end)
    full_days, rest_hours = divmod(hours, 24)
    total = full_days * Decimal(daily_chf) + min(rest_hours * Decimal(hourly_chf), Decimal(daily_chf))
    return PriceBreakdown(hours=hours, full_days=full_days, rest_hours=rest_hours, total_chf=money(total))


def validate_rate(hourly_chf: Decimal, daily_chf: Decimal) -> None:
    """A daily rate above 24 hourly rates would never apply (SPEC §4 RentalRate)."""
    if hourly_chf <= 0 or daily_chf <= 0:
        raise InvalidInput("Hourly and daily rates must be above zero.")
    if daily_chf > 24 * hourly_chf:
        raise InvalidInput(
            f"The daily rate (CHF {money(daily_chf)}) can't be more than 24 hourly rates "
            f"(CHF {money(24 * hourly_chf)})."
        )
