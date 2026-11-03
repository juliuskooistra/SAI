import bcrypt
import secrets
import uuid
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List
from sqlmodel import Session, select

from ..config import API_KEY_SECRET
from ..models.models import User, APIKey, Role
from ..timeutils import utcnow


class AuthService:
    """
    Enhanced authentication service with SQLite database and proper security.
    """

    def __init__(self):
        # Secret for API key generation, from the environment (.env on the server)
        self.api_key_secret = API_KEY_SECRET

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


    def register_user(self, username: str, email: str, password: str, db: Session,
                      role: Role = Role.customer) -> Optional[User]:
        """
        Register a new user.
        
        :param username: Username for registration
        :param email: Email for registration
        :param password: Password for registration
        :param db: Database session
        :return: UserRegistrationResponse if successful, None otherwise
        """
        # Check if username already exists
        existing_user = db.exec(select(User).filter(User.username == username)).first()
        if existing_user:
            return None

        # Check if email already exists
        existing_email = db.exec(select(User).filter(User.email == email)).first()
        if existing_email:
            return None

        # Create new user
        user_id = str(uuid.uuid4())
        hashed_password = self._hash_password(password)
        
        new_user = User(
            user_id=user_id,
            username=username,
            email=email,
            hashed_password=hashed_password,
            created_at=utcnow(),
            is_active=True,
            is_verified=True,  # Auto-verify for demo purposes
            role=role
        )
        
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return new_user

    def authenticate_user(self, username: str, password: str, db: Session) -> Optional[User]:
        """
        Authenticate a user with username and password.
        
        :param username: The username
        :param password: The password
        :param db: Database session
        :return: LoginResponse if successful, None otherwise
        """
        user = db.exec(select(User).filter(User.username == username)).first()
        if not user or not user.is_active:
            return None
            
        if not self._verify_password(password, user.hashed_password):
            return None
            
        return user

    def generate_api_key(self, username: str, name: str, expired_in_days: Optional[int], db: Session) -> tuple[str, APIKey]:
        """
        Generate a new API key for a user.
        
        :param username: The username
        :param request: API key request details
        :param db: Database session
        :return: APIKeyResponse if successful, None otherwise
        """
        user = db.exec(select(User).filter(User.username == username)).first()
        if not user or not user.is_active:
            return None

        # Generate a secure API key
        api_key = self._generate_secure_api_key()
        hashed_key = self._hash_api_key(api_key)
        
        created_at = utcnow()
        expires_at = None
        if expired_in_days:
            expires_at = created_at + timedelta(days=expired_in_days)

        # Store only the hashed key - NEVER store the plain text API key
        api_key_stored = APIKey(
            hashed_key=hashed_key,
            user_id=user.user_id,
            name=name,
            created_at=created_at,
            expires_at=expires_at,
            is_active=True,
            requests_per_minute=user.requests_per_minute,
            requests_per_hour=user.requests_per_hour,
            requests_per_day=user.requests_per_day
        )

        db.add(api_key_stored)
        db.commit()

        # Return the plain text API key only once - it won't be stored
        return api_key, api_key_stored

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
        key_record = db.exec(select(APIKey).filter(
            APIKey.hashed_key == hashed_key,
            APIKey.is_active == True
        )).first()
        
        if not key_record:
            return None

        # Check if the key has expired
        if key_record.expires_at and key_record.expires_at < utcnow():
            # Deactivate expired keys
            key_record.is_active = False
            db.commit()
            return None

        # Check if the user is still active
        user = db.exec(select(User).filter(User.user_id == key_record.user_id)).first()
        if not user or not user.is_active:
            return None

        # Update last used timestamp
        key_record.last_used = utcnow()
        db.commit()

        return key_record.user_id

    def list_user_api_keys(self, user_id: str, db: Session) -> List[APIKey]:
        """
        List all API keys for a user with usage statistics.
        
        :param username: The username
        :param db: Database session
        :return: List of API key usage info if user exists, None otherwise
        """
        return db.exec(select(APIKey).filter(APIKey.user_id == user_id)).all()


    def get_user(self, user_id: str, db: Session) -> Optional[User]:
        """Get a user by user_id."""
        return db.exec(select(User).filter(User.user_id == user_id)).first()

    def revoke_api_key(self, user_id: str, api_key_name: str, db: Session) -> bool:
        """
        Revoke the caller's active API keys with this name.
        (BikeShop fix: the reference looked the user up by a username from the
        request, and its router never called this; it returned 501.)

        :param user_id: The authenticated user's ID (from the auth middleware)
        :param api_key_name: The name of the API key to revoke
        :param db: Database session
        :return: True if at least one key was revoked, False otherwise
        """
        api_keys = db.exec(select(APIKey).filter(
            APIKey.user_id == user_id,
            APIKey.name == api_key_name,
            APIKey.is_active == True
        )).all()

        if not api_keys:
            return False

        for api_key in api_keys:
            api_key.is_active = False
        db.commit()
        return True
