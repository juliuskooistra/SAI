"""
Database configuration and models using SQLAlchemy with SQLite.
"""
from sqlmodel import SQLModel, create_engine, Session, select
import pandas as pd

from models.models import CreditScore

from loanrisk_project.scoring.scorer import ScoringService
from loanrisk_project.scoring.pricing import PricingEngine

# parquet Path
PARQUET_PATH = "./data/processed/loans_clean.parquet"
# Database setup 
# For production use, consider PostgreSQL or another robust RDBMS.
DATABASE_URL = "sqlite:///./api/credit_risk.db"
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
    with Session(engine) as session:
        # Check if the CreditScore table already has data, if so, skip seeding (this means the DB is already initialized and has data)
        exists = session.exec(select(CreditScore).limit(1)).first()
        if exists:
            return  # already seeded, prevent to run any further iniitialization code.

    # Read the first 10000 items from the parquet file and create a batch of responses
    df = pd.read_parquet(PARQUET_PATH).head(10000)
    scorer = ScoringService(artifacts_dir="artifacts")
    pricer = PricingEngine()

    result = scorer.predict_pd(df)

    prices = pricer.price_loans(
        result,
        amount_col="loan_amnt",
        term_col="term_months",
        pd_col="pd",
    )

    def to_epoch_ms(col):
        s = pd.to_datetime(col, errors="coerce")
        return (s.view("int64") // 1_000_000).astype("Int64")

    for col in ("issue_d", "earliest_cr_line"):
        if col in prices.columns:
            prices[col] = to_epoch_ms(prices[col])

    prices = prices.where(prices.notna(), None)  # NaN -> None

    try:
        with Session(engine) as session:
            objects = [CreditScore(**price) for price in prices.to_dict(orient="records")]
            session.add_all(objects)
            session.commit()
    except Exception as e:
        print(f"❌ Error initializing database: {e}")

    print("✅ Database initialized successfully!")
