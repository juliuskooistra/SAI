"""
Database configuration and models using SQLAlchemy with SQLite.
"""
from sqlmodel import SQLModel, create_engine, Session

# Database setup
DATABASE_URL = "sqlite:///./api/auth_demo.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


def create_tables():
    """Create all database tables."""
    SQLModel.metadata.create_all(bind=engine)


def get_db():
    """Get database session dependency."""
    with Session(engine) as session:
        yield session


def init_database():
    """Initialize the database and create tables if they don't exist."""
    create_tables()
    print("✅ Database initialized successfully!")
