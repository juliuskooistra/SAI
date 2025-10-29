# Split Middleware Architecture

## Overview

The authentication, billing, and rate limiting functionality has been split into three separate, modular middlewares. This provides better separation of concerns and allows for flexible application of different protection levels to different endpoint groups.

## Architecture Components

### 1. AuthenticationMiddleware (`middleware/auth_middleware.py`)
**Purpose**: Validates API keys and establishes user context

**Features**:
- Extracts API key from Authorization header
- Validates API key against database
- Sets `request.state.user_id` and `request.state.api_key_id` for downstream use
- Returns 401 for missing or invalid API keys

**Configuration**:
```python
protected_paths=["/api/", "/billing/"]  # Endpoints requiring auth
excluded_paths=["/auth/register", "/auth/login", "/docs"]  # Public endpoints
```

### 2. RateLimitMiddleware (`middleware/rate_limit_middleware.py`)
**Purpose**: Enforces rate limits for authenticated users

**Features**:
- Checks rate limits using user_id and api_key_id from request state
- Enforces per-minute, hourly, and daily limits
- Returns 429 when limits exceeded
- Requires AuthenticationMiddleware to run first

**Configuration**:
```python
protected_paths=["/api/"]  # Only API endpoints are rate limited
excluded_paths=["/auth/", "/billing/"]  # Don't rate limit auth/billing
```

### 3. BillingMiddleware (`middleware/billing_middleware_new.py`)
**Purpose**: Handles token consumption and billing

**Features**:
- Calculates token cost based on endpoint and request data
- Checks sufficient balance before processing
- Consumes tokens only on successful requests (2xx status codes)
- Logs usage analytics
- Adds billing headers to responses
- Requires AuthenticationMiddleware to run first

**Configuration**:
```python
protected_paths=["/api/"]  # Only API endpoints are billable
excluded_paths=["/auth/", "/billing/"]  # Don't bill auth/billing operations
```

## Endpoint Protection Matrix

| Endpoint Group | Authentication | Rate Limiting | Billing | Use Case |
|---------------|---------------|---------------|---------|----------|
| `/auth/*` | ❌ No | ❌ No | ❌ No | Public registration/login |
| `/billing/*` | ✅ Yes | ❌ No | ❌ No | Account management |
| `/api/*` | ✅ Yes | ✅ Yes | ✅ Yes | Billable API operations |

## Middleware Execution Order

Middlewares are applied in **reverse order** of registration. The execution flow is:

```
Request → CORS → Authentication → Rate Limiting → Billing → Endpoint
Response ← CORS ← Authentication ← Rate Limiting ← Billing ← Endpoint
```

## Implementation in main.py

```python
def _configure_middleware(self):
    # Applied in reverse order (last added executes first)
    
    # 1. Billing (for /api/* only)
    self.app.add_middleware(BillingMiddleware, 
        protected_paths=["/api/"],
        excluded_paths=["/auth/", "/billing/"])
    
    # 2. Rate Limiting (for /api/* only)  
    self.app.add_middleware(RateLimitMiddleware,
        protected_paths=["/api/"],
        excluded_paths=["/auth/", "/billing/"])
    
    # 3. Authentication (for /api/* and /billing/*)
    self.app.add_middleware(AuthenticationMiddleware,
        protected_paths=["/api/", "/billing/"],
        excluded_paths=["/auth/register", "/auth/login"])
```

## Router Simplification

### Billing Router
- **Before**: Manual authentication with `HTTPBearer` dependencies
- **After**: Uses `request.state.user_id` set by AuthenticationMiddleware
- **Benefit**: No duplicate auth logic, cleaner code

```python
# Old approach
def get_balance(self, auth_data: tuple = Depends(get_current_user_and_key)):
    user_id, _ = auth_data

# New approach  
def get_balance(self, req: Request):
    user_id, _ = get_authenticated_user(req)  # From request.state
```

### Peak Voltage Router
- **Before**: Manual billing integration in endpoint
- **After**: Pure business logic, middleware handles cross-cutting concerns
- **Benefit**: Single responsibility, easier testing

## Benefits of Split Architecture

### 1. **Modularity**
- Each middleware has a single, well-defined responsibility
- Can be developed, tested, and maintained independently
- Easy to add new middlewares or modify existing ones

### 2. **Flexibility**
- Different endpoint groups can have different protection levels
- Easy to reconfigure which endpoints get which protections
- Can disable specific middlewares for testing

### 3. **Testability**
- Each middleware can be unit tested in isolation
- Easier to mock dependencies for testing
- Clear separation makes integration testing more focused

### 4. **Performance**
- Middlewares only run for relevant endpoints
- Early exit for excluded paths
- No unnecessary processing for public endpoints

### 5. **Maintainability**
- Clear separation of concerns
- Easier to debug issues (know which middleware is responsible)
- Simpler router code focused on business logic

## Migration Notes

### Breaking Changes
- `BillingRouter` constructor no longer takes `auth_service` parameter
- Router methods now take `Request` object instead of auth dependencies
- Middleware configuration required in `main.py`

### Configuration Required
- Update `main.py` to use split middlewares
- Configure protection paths for each middleware
- Ensure correct middleware ordering

## Testing

Use `test_split_middleware.py` to verify:
- Public endpoints work without authentication
- Billing endpoints require auth but don't consume tokens
- API endpoints have full protection stack
- Rate limiting works correctly
- Token consumption happens only for billable endpoints

## Future Extensions

This architecture makes it easy to add:
- **CacheMiddleware**: Response caching for expensive operations
- **MetricsMiddleware**: Performance monitoring and analytics
- **ThrottleMiddleware**: Advanced throttling beyond simple rate limits
- **AuditMiddleware**: Detailed logging for compliance
- **CompressionMiddleware**: Response compression for large payloads

Each new middleware can be independently configured and applied to relevant endpoint groups.
