from fastapi import APIRouter, HTTPException, Depends, Request, status
from sqlmodel import Session

from ..models.models import (
    UserRegistrationRequest, UserRegistrationResponse,
    LoginRequest, LoginResponse, APIKeyRequest, APIKeyResponse, APIKeyUsageResponse, APIKeyListResponse
)
from ..services.auth_service import AuthService
from ..database import get_db


class AuthRouter:
    """
    Enhanced authentication router with user registration and database support.
    """

    def __init__(self):
        self.router = APIRouter()
        self.auth_service = AuthService()
        self._register_routes()
    

    def _register_routes(self):
        """Register all authentication routes."""
        self.router.post("/register", response_model=UserRegistrationResponse,
                         summary="Create a customer account")(self.register_user)
        self.router.post("/login", response_model=LoginResponse,
                         summary="Check a username and password")(self.login)
        self.router.post("/generate-key", response_model=APIKeyResponse,
                         summary="Get an API key with username and password")(self.create_api_key_with_credentials)
        # BikeShop: these two need the caller's API key (see main.py, protected_paths)
        self.router.get("/my-keys", response_model=APIKeyListResponse,
                        summary="List your own API keys")(self.list_my_api_keys)
        self.router.delete("/revoke-key/{key_name}",
                           summary="Revoke one of your own API keys by name")(self.revoke_api_key)


    def register_user(self, request: UserRegistrationRequest, db: Session = Depends(get_db)) -> UserRegistrationResponse:
        """
        Register a new user.
        
        :param request: User registration request
        :param db: Database session
        :return: User registration response
        :raises HTTPException: If registration fails
        """
        # Basic validation
        if len(request.password) < 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 10 characters long"
            )

        if "@" not in request.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid email format"
            )

        user = self.auth_service.register_user(request.username, request.email, request.password, db)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username or email already exists"
            )
        
        return UserRegistrationResponse(
            message="User registered successfully",
            user_id=user.user_id,
            username=user.username,
            email=user.email
        )

    def login(self, request: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
        """
        Authenticate a user and return login response.
        
        :param request: Login request with username and password
        :param db: Database session
        :return: Login response
        :raises HTTPException: If authentication fails
        """
        user = self.auth_service.authenticate_user(request.username, request.password, db)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        return LoginResponse(
            message="Login successful",
            user_id=user.user_id,
            username=user.username,
            role=user.role
        )

    def create_api_key_with_credentials(self, request: APIKeyRequest, db: Session = Depends(get_db)) -> APIKeyResponse:
        """
        Create a new API key using username/password authentication.
        
        :param request: APIKeyRequest with credentials and key details
        :param db: Database session
        :return: New API key response
        :raises HTTPException: If creation fails
        """
        # Extract credentials and API key request data
        username = request.username
        password = request.password
        name = request.name
        expires_in_days = request.expires_in_days

        if not username or not password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username and password are required"
            )

        # First authenticate the user
        user = self.auth_service.authenticate_user(username, password, db)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )

        # Generate API key using the request object (which already includes username)
        api_key, api_key_stored = self.auth_service.generate_api_key(username, name, expires_in_days, db)
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate API key"
            )

        return APIKeyResponse(
            api_key=api_key,
            name=api_key_stored.name,
            role=user.role,
            created_at=api_key_stored.created_at,
            expires_at=api_key_stored.expires_at
        )

    def list_my_api_keys(self, req: Request, db: Session = Depends(get_db)) -> APIKeyListResponse:
        """
        List all API keys for the authenticated user.

        BikeShop fix: the reference took a user_id from the request body
        without authentication, so anyone could list anyone's keys, and it
        filled the wrong field name. The user now comes from the API key
        (request.state, set by AuthenticationMiddleware).

        :param req: FastAPI request object (contains user auth from middleware)
        :param db: Database session
        :return: List of API keys with usage info
        """
        user_id = req.state.user_id
        api_keys = self.auth_service.list_user_api_keys(user_id, db)

        api_keys_response = [
            APIKeyUsageResponse(
                name=key.name,
                created_at=key.created_at,
                last_used=key.last_used,
                is_active=key.is_active
            )
            for key in api_keys
        ]
        
        return APIKeyListResponse(keys=api_keys_response)

    def revoke_api_key(self, key_name: str, req: Request, db: Session = Depends(get_db)) -> dict:
        """
        Revoke one of your own API keys by name.

        BikeShop fix: the reference always answered 501 Not Implemented.

        :param key_name: Name of the API key to revoke
        :param req: FastAPI request object (contains user auth from middleware)
        :param db: Database session
        :return: Success message
        :raises HTTPException: If no active key has that name
        """
        if not self.auth_service.revoke_api_key(req.state.user_id, key_name, db):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"You have no active API key named '{key_name}'."
            )
        return {"message": f"API key '{key_name}' revoked"}
