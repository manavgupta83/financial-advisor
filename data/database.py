# data/database.py
# Defines all database tables and provides a get_db() session factory.
# Every other module that reads/writes data imports get_db() from here.

from sqlalchemy import (
    create_engine, Column, Integer, Float, String,
    Date, DateTime, ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
from config.settings import DB_PATH

# ── Engine + session ──────────────────────────────────────────────────────────
DATABASE_URL = f"sqlite:///{DB_PATH}"
engine       = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base         = declarative_base()


def get_db():
    """Yield a database session and close it when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Table 1: Mutual fund master ───────────────────────────────────────────────
class Fund(Base):
    __tablename__ = "funds"

    id          = Column(Integer, primary_key=True, index=True)
    scheme_code = Column(Integer, unique=True, index=True, nullable=False)
    scheme_name = Column(String, nullable=False)
    fund_house  = Column(String)
    category    = Column(String)   # e.g. Large Cap, Flexi Cap, ELSS
    sub_category= Column(String)
    plan_type   = Column(String)   # Direct / Regular
    created_at  = Column(DateTime, default=datetime.utcnow)

    nav_records  = relationship("NAVHistory", back_populates="fund")
    holdings     = relationship("FundHolding", back_populates="fund")


# ── Table 2: Daily NAV history ────────────────────────────────────────────────
class NAVHistory(Base):
    __tablename__ = "nav_history"

    id          = Column(Integer, primary_key=True, index=True)
    scheme_code = Column(Integer, ForeignKey("funds.scheme_code"), nullable=False)
    nav_date    = Column(Date, nullable=False)
    nav         = Column(Float, nullable=False)

    __table_args__ = (UniqueConstraint("scheme_code", "nav_date"),)

    fund = relationship("Fund", back_populates="nav_records")


# ── Table 3: Monthly fund holdings (stocks inside each MF) ───────────────────
class FundHolding(Base):
    __tablename__ = "fund_holdings"

    id           = Column(Integer, primary_key=True, index=True)
    scheme_code  = Column(Integer, ForeignKey("funds.scheme_code"), nullable=False)
    holding_date = Column(Date, nullable=False)   # Month-end date of disclosure
    isin         = Column(String, nullable=False)
    stock_name   = Column(String)
    weight_pct   = Column(Float)                  # % of fund AUM in this stock

    __table_args__ = (UniqueConstraint("scheme_code", "holding_date", "isin"),)

    fund = relationship("Fund", back_populates="holdings")


# ── Table 4: Stock sector master ──────────────────────────────────────────────
class SectorMap(Base):
    __tablename__ = "sector_map"

    id       = Column(Integer, primary_key=True, index=True)
    isin     = Column(String, unique=True, index=True, nullable=False)
    symbol   = Column(String)
    name     = Column(String)
    sector   = Column(String)   # e.g. Financials, IT, Defence
    industry = Column(String)
    source   = Column(String)   # "nse" or "llm"


# ── Table 5: Client profiles ──────────────────────────────────────────────────
class Client(Base):
    __tablename__ = "clients"

    id             = Column(Integer, primary_key=True, index=True)
    name           = Column(String, nullable=False)
    age            = Column(Integer)
    annual_income  = Column(Float)
    monthly_expense= Column(Float)
    retirement_age = Column(Integer)
    risk_score     = Column(Float)     # Computed from questionnaire
    risk_label     = Column(String)    # Conservative / Moderate / Aggressive etc.
    created_at     = Column(DateTime, default=datetime.utcnow)

    goals    = relationship("ClientGoal", back_populates="client")
    holdings = relationship("ClientHolding", back_populates="client")


# ── Table 6: Client goals ─────────────────────────────────────────────────────
class ClientGoal(Base):
    __tablename__ = "client_goals"

    id              = Column(Integer, primary_key=True, index=True)
    client_id       = Column(Integer, ForeignKey("clients.id"), nullable=False)
    goal_name       = Column(String)    # e.g. Retirement, Child Education
    target_amount   = Column(Float)
    target_year     = Column(Integer)
    monthly_sip     = Column(Float)
    priority        = Column(String)    # High / Medium / Low
    risk_override   = Column(String)    # Optional per-goal risk override

    client = relationship("Client", back_populates="goals")


# ── Table 7: Client current holdings ─────────────────────────────────────────
class ClientHolding(Base):
    __tablename__ = "client_holdings"

    id          = Column(Integer, primary_key=True, index=True)
    client_id   = Column(Integer, ForeignKey("clients.id"), nullable=False)
    scheme_code = Column(Integer, ForeignKey("funds.scheme_code"), nullable=False)
    goal_id     = Column(Integer, ForeignKey("client_goals.id"), nullable=True)
    units       = Column(Float)
    avg_nav     = Column(Float)
    invested_amount = Column(Float)

    client = relationship("Client", back_populates="holdings")


# ── Create all tables ─────────────────────────────────────────────────────────
def init_db():
    """Create all tables if they don't exist."""
    DATA_DIR = DB_PATH.parent
    DATA_DIR.mkdir(exist_ok=True)
    Base.metadata.create_all(bind=engine)
    print(f"✅ Database initialised at {DB_PATH}")


if __name__ == "__main__":
    init_db()