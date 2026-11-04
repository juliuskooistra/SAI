from pydantic import BaseModel, ConfigDict, field_serializer, model_validator
from pydantic import Field as PField
from sqlmodel import SQLModel, Field, Column, Float, Integer, Boolean, String, text, JSON
from typing import Optional, List
from datetime import datetime, date
from decimal import Decimal
from enum import Enum

from ..config import STARTING_TOKENS, RATE_LIMIT_PER_MINUTE, RATE_LIMIT_PER_HOUR, RATE_LIMIT_PER_DAY
from ..timeutils import utcnow, to_local

"""
    The various models that are used are defined here
    These are used to define clear data structures
    If there are changes to the schema of a table in the database, these must be updated

    Tables (SQLModel, table=True) come first, then the request/response models.
    All stored times are UTC; responses show them in Zurich time (SPEC §4).
"""


######################### Enums #########################

class Role(str, Enum):
    customer = "customer"
    staff = "staff"


class Category(str, Enum):
    city = "city"
    ebike = "ebike"
    mountain = "mountain"
    road = "road"
    gravel = "gravel"
    kids = "kids"
    cargo = "cargo"


class FrameSize(str, Enum):
    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class Purpose(str, Enum):
    rental = "rental"
    sale = "sale"


class Condition(str, Enum):
    new = "new"
    used = "used"


class BikeStatus(str, Enum):
    available = "available"
    maintenance = "maintenance"   # rental bikes only
    reserved = "reserved"         # sale bikes only
    sold = "sold"                 # sale bikes only
    retired = "retired"


class RentalStatus(str, Enum):
    booked = "booked"
    active = "active"
    returned = "returned"
    cancelled = "cancelled"


class OrderStatus(str, Enum):
    reserved = "reserved"
    completed = "completed"
    cancelled = "cancelled"
    expired = "expired"


######################### Tables: users and API usage (copied from VoltagePredictor) #########################

class User(SQLModel, table=True):
    """Registered user. `role` is new compared to VoltagePredictor."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, unique=True)
    username: str = Field(index=True, unique=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str
    role: Role = Field(default=Role.customer)
    created_at: datetime = Field(default_factory=utcnow)
    is_active: bool = Field(default=True)
    is_verified: bool = Field(default=False)

    # Token billing
    token_balance: float = Field(default=STARTING_TOKENS)
    total_tokens_purchased: float = Field(default=STARTING_TOKENS)
    total_tokens_used: float = Field(default=0.0)

    # Rate limits
    requests_per_minute: int = Field(default=RATE_LIMIT_PER_MINUTE)
    requests_per_hour: int = Field(default=RATE_LIMIT_PER_HOUR)
    requests_per_day: int = Field(default=RATE_LIMIT_PER_DAY)


class APIKey(SQLModel, table=True):
    """API key, stored only as a hash."""
    id: int | None = Field(default=None, primary_key=True)
    hashed_key: str = Field(index=True, unique=True)
    user_id: str = Field(index=True)
    name: str
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime | None = Field(default=None)
    is_active: bool = Field(default=True)
    last_used: datetime | None = Field(default=None)

    # Per-key rate limits (fall back to the user's)
    requests_per_minute: int | None = Field(default=None)
    requests_per_hour: int | None = Field(default=None)
    requests_per_day: int | None = Field(default=None)


class APIUsage(SQLModel, table=True):
    """Track API usage for billing and analytics."""
    id: int | None = Field(default=None, primary_key=True)

    user_id: str = Field(index=True)
    api_key_id: int | None = Field(default=None, index=True)

    endpoint: str = Field(index=True)
    timestamp: datetime = Field(default_factory=utcnow, index=True)

    tokens_consumed: float = Field(
        default=0.0,
        sa_column=Column(Float, nullable=False, server_default="0")
    )
    request_size: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0")
    )
    response_size: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0")
    )
    processing_time_ms: int = Field(
        default=0,
        sa_column=Column(Integer, nullable=False, server_default="0")
    )
    success: bool = Field(
        default=True,
        sa_column=Column(Boolean, nullable=False, server_default=text("1"))
    )
    error_message: str | None = Field(default=None, sa_column=Column(String, nullable=True))


class TokenTransaction(SQLModel, table=True):
    """Track token purchases and adjustments."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    transaction_type: str = Field(index=True)
    amount: float
    previous_balance: float
    new_balance: float
    timestamp: datetime = Field(default_factory=utcnow, index=True)
    description: str
    reference_id: str | None = Field(default=None)


class RateLimitState(SQLModel, table=True):
    """Track rate limiting state per user/key (kept from the reference; counts come from APIUsage)."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    api_key_id: int | None = Field(default=None, index=True)
    window_type: str = Field(index=True)
    window_start: datetime = Field(index=True)
    request_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


######################### Tables: the shop (SPEC §4) #########################

class Bike(SQLModel, table=True):
    """One physical bike, either in the rental fleet or for sale."""
    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    brand: str
    category: Category = Field(index=True)
    frame_size: FrameSize
    color: str
    year: int
    purpose: Purpose = Field(index=True)
    condition: Condition = Field(default=Condition.used)
    sale_price_chf: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    status: BikeStatus = Field(default=BikeStatus.available, index=True)
    description: str = Field(default="")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class RentalRate(SQLModel, table=True):
    """The rental price list: one row per category."""
    category: Category = Field(primary_key=True)
    hourly_chf: Decimal = Field(max_digits=10, decimal_places=2)
    daily_chf: Decimal = Field(max_digits=10, decimal_places=2)
    deposit_chf: Decimal = Field(default=Decimal("0"), max_digits=10, decimal_places=2)
    updated_at: datetime = Field(default_factory=utcnow)


class Rental(SQLModel, table=True):
    """A booking of one rental bike for a period."""
    id: int | None = Field(default=None, primary_key=True)
    bike_id: int = Field(foreign_key="bike.id", index=True)
    user_id: str = Field(index=True)
    start_at: datetime = Field(index=True)
    end_at: datetime = Field(index=True)
    status: RentalStatus = Field(default=RentalStatus.booked, index=True)
    hourly_chf: Decimal = Field(max_digits=10, decimal_places=2)
    daily_chf: Decimal = Field(max_digits=10, decimal_places=2)
    quoted_price_chf: Decimal = Field(max_digits=10, decimal_places=2)
    picked_up_at: datetime | None = Field(default=None)
    returned_at: datetime | None = Field(default=None)
    final_price_chf: Decimal | None = Field(default=None, max_digits=10, decimal_places=2)
    created_at: datetime = Field(default_factory=utcnow)


class Order(SQLModel, table=True):
    """A customer's reservation of a sale bike; paid and collected in the shop."""
    __tablename__ = "orders"  # "order" is an SQL keyword
    id: int | None = Field(default=None, primary_key=True)
    bike_id: int = Field(foreign_key="bike.id", index=True)
    user_id: str = Field(index=True)
    price_chf: Decimal = Field(max_digits=10, decimal_places=2)
    status: OrderStatus = Field(default=OrderStatus.reserved, index=True)
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)
    closed_at: datetime | None = Field(default=None)


class JobRun(SQLModel, table=True):
    """Last run of each scheduled job (SPEC §5.7)."""
    name: str = Field(primary_key=True)
    last_run_at: datetime
    last_ok: bool
    last_result: str


class Job(SQLModel, table=True):
    """One unit of background work for the worker (SPEC §4 Job, §5.8)."""
    __tablename__ = "job_queue"
    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: str = Field(default="queued", index=True)       # queued | running | done | failed
    attempts: int = Field(default=0)                         # also the fencing token
    max_attempts: int = Field(default=3)
    run_after: datetime = Field(default_factory=utcnow, index=True)
    user_id: str | None = Field(default=None, index=True)    # owner; None for system jobs
    worker_id: str | None = Field(default=None)
    heartbeat_at: datetime | None = Field(default=None)
    enqueued_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)
    result: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    error: str | None = Field(default=None)


class AnalyticsEvent(SQLModel, table=True):
    """Anonymous product analytics (SPEC §4, §5.10): no user id, no IP, no time of day."""
    id: int | None = Field(default=None, primary_key=True)
    day: date = Field(index=True)
    name: str = Field(index=True)        # catalogue_view | bike_view | quote | booking | reservation
    bike_id: int | None = Field(default=None, index=True)
    category: str | None = Field(default=None)
    channel: str = Field(default="api")  # api | assistant: how, never who (SPEC §5.10)


######################### Shop: request/response models #########################

class LocalTimes(BaseModel):
    """Base for responses: every datetime field is shown in Zurich time."""
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("*", when_used="json")
    def _local(self, value):
        if isinstance(value, datetime):
            return to_local(value).isoformat()
        return value


class RentalRateResponse(LocalTimes):
    category: Category
    hourly_chf: Decimal = PField(description="Price per started hour, CHF", examples=["8.00"])
    daily_chf: Decimal = PField(description="Cap per 24 hours, CHF", examples=["35.00"])
    deposit_chf: Decimal = PField(description="The most the deposit can be, CHF: twice the rental price, "
                                              "capped at this", examples=["100.00"])


class BikeResponse(LocalTimes):
    id: int
    code: str = PField(description="Code on the frame sticker", examples=["R-EBIKE-03"])
    name: str
    brand: str
    category: Category
    frame_size: FrameSize
    color: str
    year: int
    purpose: Purpose = PField(description="'rental' bikes are rented out, 'sale' bikes are for sale")
    condition: Condition
    sale_price_chf: Optional[Decimal] = PField(default=None, description="Price for sale bikes, CHF; null for rental bikes")
    status: BikeStatus
    description: str


class BikeDetailResponse(BikeResponse):
    rental_rate: Optional[RentalRateResponse] = PField(default=None, description="Price list entry, for rental bikes")


class BikeCreateRequest(BaseModel):
    code: str = PField(min_length=1, examples=["S-ROAD-12"])
    name: str = PField(min_length=1, examples=["Canyon Endurace 7"])
    brand: str = PField(min_length=1, examples=["Canyon"])
    category: Category
    frame_size: FrameSize
    color: str = PField(min_length=1, examples=["blue"])
    year: int = PField(ge=1990, le=2100, examples=[2025])
    purpose: Purpose
    condition: Condition = Condition.used
    sale_price_chf: Optional[Decimal] = PField(default=None, gt=0, max_digits=10, decimal_places=2,
                                               description="Required for sale bikes, must be empty for rental bikes")
    description: str = ""

    @model_validator(mode="after")
    def _price_matches_purpose(self):
        if self.purpose == Purpose.sale and self.sale_price_chf is None:
            raise ValueError("A bike for sale needs a sale price.")
        if self.purpose == Purpose.rental and self.sale_price_chf is not None:
            raise ValueError("A rental bike has no sale price; its price comes from the rental price list.")
        if self.purpose == Purpose.rental and self.condition == Condition.new:
            self.condition = Condition.used
        return self


class BikeUpdateRequest(BaseModel):
    """Fields to change; leave out what stays the same. Status: only available <-> maintenance (rental bikes)."""
    name: Optional[str] = PField(default=None, min_length=1)
    brand: Optional[str] = PField(default=None, min_length=1)
    category: Optional[Category] = None
    frame_size: Optional[FrameSize] = None
    color: Optional[str] = PField(default=None, min_length=1)
    year: Optional[int] = PField(default=None, ge=1990, le=2100)
    condition: Optional[Condition] = None
    sale_price_chf: Optional[Decimal] = PField(default=None, gt=0, max_digits=10, decimal_places=2)
    status: Optional[BikeStatus] = PField(default=None, description="'available' or 'maintenance' (rental bikes)")
    description: Optional[str] = None


class RentalRateRequest(BaseModel):
    hourly_chf: Decimal = PField(gt=0, max_digits=10, decimal_places=2, examples=["8.00"])
    daily_chf: Decimal = PField(gt=0, max_digits=10, decimal_places=2, examples=["35.00"])
    deposit_chf: Decimal = PField(default=Decimal("0"), ge=0, max_digits=10, decimal_places=2, examples=["100.00"],
                                  description="Deposit cap, CHF: the deposit is twice the price, at most this")


class OpeningDay(BaseModel):
    weekday: str = PField(examples=["Monday"])
    opens: Optional[str] = PField(default=None, description="HH:MM, null when closed", examples=["09:00"])
    closes: Optional[str] = PField(default=None, examples=["18:30"])


class ClosedDay(BaseModel):
    date: date
    reason: str = PField(examples=["Christmas Day"])


class OpeningHoursResponse(BaseModel):
    timezone: str = "Europe/Zurich"
    weekly: List[OpeningDay]
    closed_days: List[ClosedDay] = PField(description="Upcoming public holidays on which the shop is closed")
    rules: List[str] = PField(description="Booking rules in plain words")


class RentalPeriodRequest(BaseModel):
    bike_id: int = PField(description="Id of a rental bike", examples=[3])
    start_at: datetime = PField(description="Pick-up time, ISO 8601; without offset it is Zurich time",
                                examples=["2026-11-07T10:00:00+01:00"])
    end_at: datetime = PField(description="Return time, ISO 8601; without offset it is Zurich time",
                              examples=["2026-11-07T15:00:00+01:00"])


class QuoteResponse(LocalTimes):
    bike_id: int
    category: Category
    start_at: datetime
    end_at: datetime
    hours: int = PField(description="Started hours, rounded up")
    full_days: int = PField(description="Number of full 24-hour blocks")
    rest_hours: int = PField(description="Hours after the full days")
    hourly_chf: Decimal
    daily_chf: Decimal
    total_chf: Decimal = PField(description="full_days x daily + min(rest_hours x hourly, daily)")
    deposit_chf: Decimal = PField(description="min(2 x total_chf, the category's cap), taken at pick-up "
                                              "and paid back on return")


class AvailableBike(LocalTimes):
    bike: BikeResponse
    quote: QuoteResponse


class AvailabilityResponse(LocalTimes):
    start_at: datetime
    end_at: datetime
    bikes: List[AvailableBike]


class RentalResponse(LocalTimes):
    id: int
    bike_id: int
    bike_code: str
    bike_name: str
    user_id: str
    username: Optional[str] = PField(default=None, description="Shown to staff only")
    start_at: datetime
    end_at: datetime
    status: RentalStatus
    hourly_chf: Decimal
    daily_chf: Decimal
    quoted_price_chf: Decimal
    picked_up_at: Optional[datetime] = None
    returned_at: Optional[datetime] = None
    final_price_chf: Optional[Decimal] = None
    overdue: bool = PField(default=False, description="Active and past its return time")
    at_risk: bool = PField(default=False, description="Booked, but the bike is in maintenance")
    created_at: datetime


class OrderRequest(BaseModel):
    bike_id: int = PField(description="Id of a sale bike", examples=[25])


class OrderResponse(LocalTimes):
    id: int
    bike_id: int
    bike_code: str
    bike_name: str
    user_id: str
    username: Optional[str] = PField(default=None, description="Shown to staff only")
    price_chf: Decimal
    status: OrderStatus
    expires_at: datetime = PField(description="The bike is held until then; afterwards it is released")
    created_at: datetime
    closed_at: Optional[datetime] = None


class InventoryCount(BaseModel):
    purpose: Purpose
    category: Category
    status: BikeStatus
    count: int


class InventorySummary(LocalTimes):
    counts: List[InventoryCount]
    rental_bikes_out_now: int
    overdue_rentals: List[RentalResponse]
    at_risk_bookings: List[RentalResponse]
    orders_expiring_within_24h: List[OrderResponse]


class JobStatus(LocalTimes):
    last_run_at: Optional[datetime] = None
    last_ok: Optional[bool] = None
    last_result: Optional[str] = None


class WorkerStatus(LocalTimes):
    last_seen: Optional[datetime] = PField(default=None, description="When the worker last polled the queue "
                                                                     "(updated at most every 30 s)")


class HealthResponse(LocalTimes):
    status: str = "ok"
    database: str
    inference: str = PField(description="ok | unreachable | unauthorized | model_missing | not_configured")
    scheduler: JobStatus = PField(description="Last run of the reservation expiry (run by the worker, SPEC §5.7)")
    worker: WorkerStatus = PField(default_factory=WorkerStatus)
    queue: dict[str, int] = PField(default_factory=dict, description="Jobs by status: queued, running, done, failed",
                                   examples=[{"queued": 0, "running": 0, "done": 12, "failed": 0}])


######################### Default models (from VoltagePredictor) #########################


# Authentication Models
class UserRegistrationRequest(BaseModel):
    """
    Request model for user registration
    """
    username: str
    email: str
    password: str


class UserRegistrationResponse(BaseModel):
    """
    Response model for user registration
    """
    message: str
    user_id: str
    username: str
    email: str


class LoginRequest(BaseModel):
    """
    Request model for user login
    """
    username: str
    password: str


class LoginResponse(BaseModel):
    """
    Response model for successful login
    """
    message: str
    user_id: str
    username: str
    role: Role


class APIKeyRequest(LoginRequest):
    """
    Request model for API key generation with credentials
    """
    name: str  # Friendly name for the API key
    expires_in_days: Optional[int] = 30  # Default 30 days


class APIKeyResponse(BaseModel):
    """
    Response model for API key generation
    """
    api_key: str
    name: str
    role: Role
    created_at: datetime
    expires_at: Optional[datetime] = None


class APIKeyUsageResponse(BaseModel):
    """
    Response model for API key usage statistics
    """
    name: str
    created_at: datetime
    last_used: Optional[datetime] = None
    is_active: bool


class APIKeyListResponse(BaseModel):
    """
    Response model for listing API keys
    """
    keys: List[APIKeyUsageResponse]


# Billing and Usage Models
class TokenPurchaseRequest(BaseModel):
    """
    Request model for purchasing tokens
    """
    amount: float
    payment_method: str = "demo"  # For demo purposes


class TokenPurchaseResponse(BaseModel):
    """
    Response model for token purchase
    """
    message: str
    tokens_added: float
    new_balance: float
    transaction_id: str


class EndpointUsage(BaseModel):
    """
    Usage statistics for a specific endpoint
    """
    endpoint: str
    requests: int
    tokens: float


class UsageStatsResponse(BaseModel):
    """
    Response model for usage statistics
    """
    period_days: int
    current_balance: float
    total_requests: int
    total_tokens_consumed: float
    endpoint_breakdown: List[EndpointUsage]


class RateLimitStatus(BaseModel):
    """
    Rate limit status response
    """
    limits: dict
    current_usage: dict
    remaining: dict


class BalanceResponse(BaseModel):
    """
    Response model for user balance
    """
    current_balance: float
    total_purchased: float
    total_used: float
    username: str
