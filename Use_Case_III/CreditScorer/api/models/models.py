from pydantic import BaseModel, ConfigDict
from sqlmodel import SQLModel, Field, Column, Float, Integer, Boolean, String, text
from typing import Optional, List
from datetime import datetime
import uuid

"""
    The various models that are used are defined here
    These are used to define clear data structures
    If there are changes to the schema of a table in the database, these must be updated
"""
# 1) Shared fields (no table=True, no defaults beyond None)
class CreditScoreBase(SQLModel):
    loan_amnt: Optional[int] = None
    term: Optional[int] = None
    int_rate: Optional[float] = None
    installment: Optional[float] = None
    grade: Optional[str] = None
    sub_grade: Optional[str] = None
    emp_title: Optional[str] = None
    emp_length: Optional[str] = None
    home_ownership: Optional[str] = None
    annual_inc: Optional[float] = None
    verification_status: Optional[str] = None
    issue_d: Optional[int] = None             # use date/datetime if it’s a date
    purpose: Optional[str] = None
    title: Optional[str] = None
    zip_code: Optional[str] = None
    addr_state: Optional[str] = None
    dti: Optional[float] = None
    delinq_2yrs: Optional[int] = None
    earliest_cr_line: Optional[int] = None    # date/datetime as well
    fico_range_low: Optional[int] = None
    fico_range_high: Optional[int] = None
    inq_last_6mths: Optional[int] = None
    mths_since_last_delinq: Optional[int] = None
    mths_since_last_record: Optional[int] = None
    open_acc: Optional[int] = None
    pub_rec: Optional[int] = None
    revol_bal: Optional[int] = None
    revol_util: Optional[float] = None
    total_acc: Optional[int] = None
    term_months: Optional[int] = None
    emp_length_years: Optional[float] = None # changed to float
    fico_mid: Optional[float] = None    # changed to float
    credit_hist_months: Optional[float] = None
    income_to_loan: Optional[float] = None
    revol_util_ratio: Optional[float] = None
    dti_bucket: Optional[str] = None
    zip3: Optional[str] = None
    region: Optional[str] = None


# 2) Small mixins for add-on fields (still no table=True)
class IdMixin(SQLModel):
    id: uuid.UUID


class OptionalIdMixin(SQLModel):
    id: Optional[uuid.UUID] = None


class PredictionsMixin(SQLModel):
    pd: Optional[float] = None
    apr: Optional[float] = None
    origination_fee: Optional[float] = None
    monthly_payment: Optional[float] = None
    expected_investor_apy: Optional[float] = None


# 3) DB table model — the ONLY class with table=True
class CreditScore(CreditScoreBase, IdMixin, PredictionsMixin, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)


# 4) API DTOs (no table=True ⇒ no JSON schema warnings)
class CreditScoreRequest(CreditScoreBase, OptionalIdMixin):
    # Accept ORM objects when returning/echoing from services if needed
    model_config = ConfigDict(from_attributes=True)


class CreditScoreResponse(CreditScoreBase, IdMixin, PredictionsMixin):
    # Convert ORM -> DTO cleanly
    model_config = ConfigDict(from_attributes=True)


class CreditScoreListRequest(BaseModel):
    """
    Request model for a list of scoring data
    """
    data: List[CreditScoreRequest]


class CreditScoreListResponse(BaseModel):
    """
    Response model for a list of scoring data
    """
    data: List[CreditScoreResponse]



class PortfolioRequest(BaseModel):
    """
    Request model for portfolio optimization
    """
    budget: float
    note_size: float
    max_weight: float
    min_loans: int
    grade_cap: float
    state_cap: Optional[float] = None


class PortfolioResponse(BaseModel):
    """
    Response model for portfolio optimization
    """
    portfolio: List[CreditScore]
    summary: dict

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