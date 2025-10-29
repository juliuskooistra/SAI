from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, List
from sqlmodel import Session

from models.models import (
    UserRegistrationRequest, UserRegistrationResponse,
    LoginRequest, LoginResponse, 
    APIKeyRequest, APIKeyResponse, APIKeyUsageResponse
)
from services.auth_service import AuthService
from database import get_db
from models.models import APIKey


class AuthRouter:
    """
    Enhanced authentication router with user registration and database support.
    """

    def __init__(self):
        self.router = APIRouter()
        self.auth_service = AuthService()
        self.security = HTTPBearer(auto_error=False)
        self._register_routes()

    def _register_routes(self):
        """Register all authentication routes."""
        self.router.post("/register", response_model=UserRegistrationResponse)(self.register_user)
        self.router.post("/login", response_model=LoginResponse)(self.login)
        self.router.post("/generate-key", response_model=APIKeyResponse)(self.create_api_key_with_credentials)
        self.router.get("/my-keys")(self.list_my_api_keys)
        self.router.delete("/revoke-key/{key_name}")(self.revoke_api_key)

    def get_current_user_dependency(self):
        """Return the dependency function for current user authentication."""
        def dependency(credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False)),
                      db: Session = Depends(get_db)) -> str:
            """
            Dependency to get the current authenticated user from API key.
            """
            if not credentials:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Missing API key",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            user_id = self.auth_service.validate_api_key(credentials.credentials, db)
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired API key",
                    headers={"WWW-Authenticate": "Bearer"},
                )

            return user_id
        
        return dependency

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

        response = self.auth_service.register_user(request, db)
        if not response:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username or email already exists"
            )
        
        return response

    def login(self, request: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
        """
        Authenticate a user and return login response.
        
        :param request: Login request with username and password
        :param db: Database session
        :return: Login response
        :raises HTTPException: If authentication fails
        """
        response = self.auth_service.authenticate_user(request.username, request.password, db)
        if not response:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )
        
        return response

    def create_api_key_with_credentials(self, request: dict, db: Session = Depends(get_db)) -> APIKeyResponse:
        """
        Create a new API key using username/password authentication.
        Expected request format:
        {
            "username": "string",
            "password": "string", 
            "api_key_name": "string",
            "expires_in_days": 30
        }
        
        :param request: Combined login and API key creation request
        :param db: Database session
        :return: New API key response
        :raises HTTPException: If creation fails
        """
        # Extract credentials and API key request data
        username = request.get("username")
        password = request.get("password")
        api_key_name = request.get("api_key_name", "Default API Key")
        expires_in_days = request.get("expires_in_days", 30)

        if not username or not password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Username and password are required"
            )

        # First authenticate the user
        auth_response = self.auth_service.authenticate_user(username, password, db)
        if not auth_response:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password"
            )

        # Generate API key
        api_key_request = APIKeyRequest(name=api_key_name, expires_in_days=expires_in_days)
        api_key_response = self.auth_service.generate_api_key(username, api_key_request, db)
        if not api_key_response:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate API key"
            )

        return api_key_response

    def list_my_api_keys(self, 
                        request: dict,
                        db: Session = Depends(get_db)) -> List[APIKeyUsageResponse]:
        """
        List all API keys for the authenticated user.
        
        :param user_id: Current authenticated user ID
        :param db: Database session
        :return: List of API keys with usage info
        :raises HTTPException: If listing fails
        """
        user_id = request.get("user_id")
        print(user_id)
        # This is a simplified version - in a real app you'd get username from user_id
        # For now, we'll require username in the query params
        api_keys = db.query(APIKey).filter(APIKey.user_id == user_id).all()

        if not api_keys:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No API keys found for the current user."
            )
            
        return [APIKeyUsageResponse(**key) for key in api_keys]



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
