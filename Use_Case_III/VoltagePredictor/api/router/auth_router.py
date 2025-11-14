from fastapi import APIRouter, HTTPException, Depends, status
from sqlmodel import Session

from ..models.models import (
    UserRegistrationRequest, UserRegistrationResponse,
    LoginRequest, LoginResponse, APIKeyRequest, APIKeyResponse, APIKeyUsageResponse, APIKeyListRequest, APIKeyListResponse
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
        self.router.post("/register", response_model=UserRegistrationResponse)(self.register_user)
        self.router.post("/login", response_model=LoginResponse)(self.login)
        self.router.post("/generate-key", response_model=APIKeyResponse)(self.create_api_key_with_credentials)
        self.router.get("/my-keys")(self.list_my_api_keys)
        self.router.delete("/revoke-key/{key_name}")(self.revoke_api_key)


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
            username=user.username
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
            created_at=api_key_stored.created_at,
            expires_at=api_key_stored.expires_at
        )

    def list_my_api_keys(self, 
                        request: APIKeyListRequest,
                        db: Session = Depends(get_db)) -> APIKeyListResponse:
        """
        List all API keys for the authenticated user.
        
        :param user_id: Current authenticated user ID
        :param db: Database session
        :return: List of API keys with usage info
        :raises HTTPException: If listing fails
        """
        user_id = request.user_id
        api_keys = self.auth_service.list_user_api_keys(user_id, db)

        if not api_keys:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No API keys found for the current user."
            )
        
        api_keys_response = [
            APIKeyUsageResponse(
                api_key_name=key.name,
                created_at=key.created_at,
                last_used=key.last_used,
                is_active=key.is_active
            )
            for key in api_keys
        ]
        
        return APIKeyListResponse(keys=api_keys_response)



    def revoke_api_key(self, 
                      key_name: str,
                      user_id: str = Depends(lambda self=None: self.get_current_user if self else None),
                      db: Session = Depends(get_db)) -> dict:
        """
        Revoke an API key by name.
        
        :param key_name: Name of the API key to revoke
        :param user_id: Current authenticated user ID
        :param db: Database session
        :return: Success message
        :raises HTTPException: If revocation fails
        """
        # This is a simplified version - in a real app you'd get username from user_id
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="This endpoint requires authentication system improvements. Keys expire automatically for now."
        )
