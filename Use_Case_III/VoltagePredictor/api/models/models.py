from pydantic import BaseModel
from sqlmodel import SQLModel, Field, Column, Float, Integer, Boolean, String, text
from typing import Optional, List
from datetime import datetime

"""
    The various models that are used are defined here
    These are used to define clear data structures
    If there are changes to the schema of a table in the database, these must be updated
"""
class PeakVoltageRequest(BaseModel):
    """
    Request model for a list of peak voltage data
    """
    kW_surplus: Optional[float] = None
    kWp: Optional[float] = None
    pvsystems_count: Optional[float] = None
    ta: Optional[float] = None
    gh: Optional[float] = None
    dd: Optional[float] = None
    rr: Optional[float] = None
    hour_sin: Optional[float] = None
    hour_cos: Optional[float] = None
    week_sin: Optional[float] = None
    week_cos: Optional[float] = None
    weekday_sin: Optional[float] = None
    weekday_cos: Optional[float] = None
    UW: Optional[float] = None

class PeakVoltageListRequest(BaseModel):
    """
    Request model for a list of peak voltage data
    """
    data: List[PeakVoltageRequest]
    return_scaled: Optional[bool] = False


class PeakVoltageResponse(PeakVoltageRequest):
    """
    Response model for peak voltage data
    """
    U_max: float

class PeakVoltageListResponse(BaseModel):
    """
    Response model for a list of peak voltage data
    """
    data: List[PeakVoltageResponse]

######################### Authentication, Billing, Rate Limiting Models #########################

class User(SQLModel, table=True):
    """User model for authentication."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True, unique=True)
    username: str = Field(index=True, unique=True)
    email: str = Field(index=True, unique=True)
    hashed_password: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_active: bool = Field(default=True)
    is_verified: bool = Field(default=False)

    # Token/Billing System
    token_balance: float = Field(default=100.0)
    total_tokens_purchased: float = Field(default=100.0)
    total_tokens_used: float = Field(default=0.0)

    # Rate Limiting
    requests_per_minute: int = Field(default=10)
    requests_per_hour: int = Field(default=100)
    requests_per_day: int = Field(default=1000)


class APIKey(SQLModel, table=True):
    """API Key model for storing user API keys."""
    id: int | None = Field(default=None, primary_key=True)
    hashed_key: str = Field(index=True, unique=True)
    user_id: str = Field(index=True)
    name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime | None = Field(default=None)
    is_active: bool = Field(default=True)
    last_used: datetime | None = Field(default=None)

    # Rate limiting per key (optional override of user limits)
    requests_per_minute: int | None = Field(default=None)
    requests_per_hour: int | None = Field(default=None)
    requests_per_day: int | None = Field(default=None)



class APIUsage(SQLModel, table=True):
    """Track API usage for billing and analytics."""
    id: int | None = Field(default=None, primary_key=True)

    user_id: str = Field(index=True)
    api_key_id: int | None = Field(default=None, index=True)  # make nullable if it can be missing

    endpoint: str = Field(index=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)

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
    # prefer integer ms for portability
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
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    description: str
    reference_id: str | None = Field(default=None)



class RateLimitState(SQLModel, table=True):
    """Track rate limiting state per user/key."""
    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    api_key_id: int | None = Field(default=None, index=True)
    window_type: str = Field(index=True)
    window_start: datetime = Field(index=True)
    request_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)



######################### Default models #########################


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
    created_at: datetime
    expires_at: Optional[datetime] = None

class APIKeyListRequest(BaseModel):
    """
    Request model for listing API keys
    """
    user_id: str

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


class UsageStatsRequest(BaseModel):
    """
    Request model for usage statistics
    """
    days: int = 30  # Default last 30 days


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


class TokenTransactionHistory(BaseModel):
    """
    Token transaction history item
    """
    transaction_type: str
    amount: float
    timestamp: datetime
    description: str
    balance_after: float

class BalanceResponse(BaseModel):
    """
    Response model for user balance
    """
    current_balance: float
    total_purchased: float
    total_used: float
    username: str