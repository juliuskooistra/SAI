import bcrypt
import secrets
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List
from sqlmodel import Session

from models.models import (
    UserRegistrationRequest, UserRegistrationResponse, 
    LoginResponse, APIKeyRequest, APIKeyResponse, APIKeyUsageResponse, User, APIKey
)


class AuthService:
    """
    Enhanced authentication service with SQLite database and proper security.
    """

    def __init__(self):
        # Secret for API key generation (in production, use environment variable)
        self.api_key_secret = "demo-secret-key-change-in-production"

    def _hash_password(self, password: str) -> str:
        """Hash a password using bcrypt."""
        salt = bcrypt.gensalt()
        return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

    def _verify_password(self, password: str, hashed_password: str) -> bool:
        """Verify a password against its bcrypt hash."""
        return bcrypt.checkpw(password.encode('utf-8'), hashed_password.encode('utf-8'))

    def _generate_secure_api_key(self) -> str:
        """Generate a cryptographically secure API key."""
        # Generate a secure random key
        random_bytes = secrets.token_bytes(32)
        # Create a deterministic but unique key using the secret
        key_data = f"{random_bytes.hex()}{self.api_key_secret}".encode('utf-8')
        key_hash = hashlib.sha256(key_data).hexdigest()
        return f"pk_{key_hash[:32]}"

    def _hash_api_key(self, api_key: str) -> str:
        """Hash an API key for secure storage."""
        return hashlib.sha256(f"{api_key}{self.api_key_secret}".encode('utf-8')).hexdigest()

    def register_user(self, request: UserRegistrationRequest, db: Session) -> Optional[UserRegistrationResponse]:
        """
        Register a new user.
        
        :param request: User registration request
        :param db: Database session
        :return: UserRegistrationResponse if successful, None otherwise
        """
        # Check if username already exists
        existing_user = db.query(User).filter(User.username == request.username).first()
        if existing_user:
            return None

        # Check if email already exists
        existing_email = db.query(User).filter(User.email == request.email).first()
        if existing_email:
            return None

        # Create new user
        user_id = str(uuid.uuid4())
        hashed_password = self._hash_password(request.password)
        
        new_user = User(
            user_id=user_id,
            username=request.username,
            email=request.email,
            hashed_password=hashed_password,
            created_at=datetime.utcnow(),
            is_active=True,
            is_verified=True  # Auto-verify for demo purposes
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return UserRegistrationResponse(
            message="User registered successfully",
            user_id=user_id,
            username=request.username,
            email=request.email
        )

    def authenticate_user(self, username: str, password: str, db: Session) -> Optional[LoginResponse]:
        """
        Authenticate a user with username and password.
        
        :param username: The username
        :param password: The password
        :param db: Database session
        :return: LoginResponse if successful, None otherwise
        """
        user = db.query(User).filter(User.username == username).first()
        if not user or not user.is_active:
            return None
            
        if not self._verify_password(password, user.hashed_password):
            return None
            
        return LoginResponse(
            message="Login successful",
            user_id=user.user_id,
            username=user.username
        )

    def generate_api_key(self, username: str, request: APIKeyRequest, db: Session) -> Optional[APIKeyResponse]:
        """
        Generate a new API key for a user.
        
        :param username: The username
        :param request: API key request details
        :param db: Database session
        :return: APIKeyResponse if successful, None otherwise
        """
        user = db.query(User).filter(User.username == username).first()
        if not user or not user.is_active:
            return None

        # Generate a secure API key
        api_key = self._generate_secure_api_key()
        hashed_key = self._hash_api_key(api_key)
        
        created_at = datetime.utcnow()
        expires_at = None
        if request.expires_in_days:
            expires_at = created_at + timedelta(days=request.expires_in_days)

        # Store only the hashed key - NEVER store the plain text API key
        new_api_key = APIKey(
            hashed_key=hashed_key,
            user_id=user.user_id,
            name=request.name,
            created_at=created_at,
            expires_at=expires_at,
            is_active=True,
            requests_per_minute=user.requests_per_minute,
            requests_per_hour=user.requests_per_hour,
            requests_per_day=user.requests_per_day
        )

        db.add(new_api_key)
        db.commit()

        # Return the plain text API key only once - it won't be stored
        return APIKeyResponse(
            api_key=api_key,  # This is the only time we return the plain text key
            name=request.name,
            created_at=created_at,
            expires_at=expires_at
        )

    def validate_api_key(self, api_key: str, db: Session) -> Optional[str]:
        """
        Validate an API key and return the associated user ID.
        
        :param api_key: The API key to validate (plain text from request)
        :param db: Database session
        :return: User ID if valid, None otherwise
        """
        # Hash the provided API key to compare with stored hashes
        hashed_key = self._hash_api_key(api_key)
        
        # Look up the key by its hash - we never store plain text keys
        key_record = db.query(APIKey).filter(
            APIKey.hashed_key == hashed_key,
            APIKey.is_active == True
        ).first()
        
        if not key_record:
            return None

        # Check if the key has expired
        if key_record.expires_at and key_record.expires_at < datetime.utcnow():
            # Deactivate expired keys
            key_record.is_active = False
            db.commit()
            return None

        # Check if the user is still active
        user = db.query(User).filter(User.user_id == key_record.user_id).first()
        if not user or not user.is_active:
            return None

        # Update last used timestamp
        key_record.last_used = datetime.utcnow()
        db.commit()

        return key_record.user_id

    def list_user_api_keys(self, username: str, db: Session) -> Optional[List[APIKeyUsageResponse]]:
        """
        List all API keys for a user with usage statistics.
        
        :param username: The username
        :param db: Database session
        :return: List of API key usage info if user exists, None otherwise
        """
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return None

        api_keys = db.query(APIKey).filter(APIKey.user_id == user.user_id).all()
        
        return [
            APIKeyUsageResponse(
                api_key_name=key.name,
                created_at=key.created_at,
                last_used=key.last_used,
                is_active=key.is_active
            )
            for key in api_keys
        ]

    def revoke_api_key(self, username: str, api_key_name: str, db: Session) -> bool:
        """
        Revoke an API key by name.
        
        :param username: The username
        :param api_key_name: The name of the API key to revoke
        :param db: Database session
        :return: True if revoked successfully, False otherwise
        """
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return False

        api_key = db.query(APIKey).filter(
            APIKey.user_id == user.user_id,
            APIKey.name == api_key_name
        ).first()
        
        if not api_key:
            return False

        api_key.is_active = False
        db.commit()
        return True
