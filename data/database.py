# data/database.py
# Defines all database tables and provides a get_db() session factory.
# Every other module that reads/writes data imports get_db() from here.
#
# Phase 5 fix: added missing columns to Client and ClientGoal that were
# written by client_manager.py but absent from ORM model — caused silent
# failures on fresh Streamlit Cloud deploys (init_db() didn't create them).
# Added _run_migrations() for safe ALTER TABLE on existing DBs.
#
# Scope v3 additions: fund_summaries, overlap_cache, pending_preferences,
# agent_runs, reports, orders, users (placeholder), advisor_clients (placeholder)
# + client_holdings tx history columns (isin, scheme_name, purchase_date, purchase_cost, units_bought)
#
# Phase 6 fix: added AuditLog ORM model (was in schema docs but missing from code)
# + otp_issued_at migration for users table

from sqlalchemy import (
    create_engine, Column, Integer, Float, String,
    Date, DateTime, ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
from config.settings import DB_PATH
import sqlite3
import logging

logger = logging.getLogger(__name__)

# -- Engine + session ---------------------------------------------------------
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


# -- Table 1: Mutual fund master ----------------------------------------------
class Fund(Base):
    __tablename__ = "funds"

    id          = Column(Integer, primary_key=True, index=True)
    scheme_code = Column(Integer, unique=True, index=True, nullable=False)
    scheme_name = Column(String, nullable=False)
    fund_house  = Column(String)
    category    = Column(String)
    sub_category= Column(String)
    plan_type   = Column(String)
    created_at  = Column(DateTime, default=datetime.utcnow)

    nav_records  = relationship("NAVHistory", back_populates="fund")
    holdings     = relationship("FundHolding", back_populates="fund")


# -- Table 2: Daily NAV history -----------------------------------------------
class NAVHistory(Base):
    __tablename__ = "nav_history"

    id          = Column(Integer, primary_key=True, index=True)
    scheme_code = Column(Integer, ForeignKey("funds.scheme_code"), nullable=False)
    nav_date    = Column(Date, nullable=False)
    nav         = Column(Float, nullable=False)

    __table_args__ = (UniqueConstraint("scheme_code", "nav_date"),)

    fund = relationship("Fund", back_populates="nav_records")


# -- Table 3: Monthly fund holdings (stocks inside each MF) ------------------
class FundHolding(Base):
    __tablename__ = "fund_holdings"

    id           = Column(Integer, primary_key=True, index=True)
    scheme_code  = Column(Integer, ForeignKey("funds.scheme_code"), nullable=False)
    holding_date = Column(Date, nullable=False)
    isin         = Column(String, nullable=False)
    stock_name   = Column(String)
    weight_pct   = Column(Float)

    __table_args__ = (UniqueConstraint("scheme_code", "holding_date", "isin"),)

    fund = relationship("Fund", back_populates="holdings")


# -- Table 4: Stock sector master ---------------------------------------------
class SectorMap(Base):
    __tablename__ = "sector_map"

    id       = Column(Integer, primary_key=True, index=True)
    isin     = Column(String, unique=True, index=True, nullable=False)
    symbol   = Column(String)
    name     = Column(String)
    sector   = Column(String)
    industry = Column(String)
    source   = Column(String)


# -- Table 5: Client profiles -------------------------------------------------
class Client(Base):
    __tablename__ = "clients"

    id              = Column(Integer, primary_key=True, index=True)
    name            = Column(String, nullable=False)
    age             = Column(Integer)
    annual_income   = Column(Float)
    monthly_income  = Column(Float)
    monthly_expense = Column(Float)
    retirement_age  = Column(Integer)
    dependants      = Column(Integer, default=0)
    email           = Column(String)
    phone           = Column(String)
    pan             = Column(String)
    risk_score      = Column(Float)
    risk_label      = Column(String)
    risk_profile    = Column(String)
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    goals    = relationship("ClientGoal", back_populates="client")
    holdings = relationship("ClientHolding", back_populates="client")


# -- Table 6: Client goals ----------------------------------------------------
class ClientGoal(Base):
    __tablename__ = "client_goals"

    id              = Column(Integer, primary_key=True, index=True)
    client_id       = Column(Integer, ForeignKey("clients.id"), nullable=False)
    goal_name       = Column(String)
    goal_type       = Column(String)
    target_amount   = Column(Float)
    target_year     = Column(Integer)
    current_savings = Column(Float, default=0.0)
    monthly_sip     = Column(Float)
    priority        = Column(String)
    risk_override   = Column(String)

    client = relationship("Client", back_populates="goals")


# -- Table 7: Client current holdings -----------------------------------------
# Extended with tx history columns for statement ingestion (scope 1.6 / 4.6)
class ClientHolding(Base):
    __tablename__ = "client_holdings"

    id              = Column(Integer, primary_key=True, index=True)
    client_id       = Column(Integer, ForeignKey("clients.id"), nullable=False)
    scheme_code     = Column(Integer, ForeignKey("funds.scheme_code"), nullable=True)
    goal_id         = Column(Integer, ForeignKey("client_goals.id"), nullable=True)
    isin            = Column(String)
    scheme_name     = Column(String)
    units           = Column(Float)
    avg_nav         = Column(Float)
    invested_amount = Column(Float)
    purchase_date   = Column(String)
    purchase_cost   = Column(Float)
    units_bought    = Column(Float)

    client = relationship("Client", back_populates="holdings")


# -- Table 8: AI-generated fund summaries -------------------------------------
class FundSummary(Base):
    __tablename__ = "fund_summaries"

    id             = Column(Integer, primary_key=True, index=True)
    scheme_code    = Column(Integer, unique=True, index=True, nullable=False)
    scheme_name    = Column(String)
    summary_text   = Column(Text)
    source_doc_url = Column(String)
    generated_at   = Column(DateTime)
    quarter        = Column(String)


# -- Table 9: Cached overlap results ------------------------------------------
class OverlapCache(Base):
    __tablename__ = "overlap_cache"

    id                    = Column(Integer, primary_key=True, index=True)
    client_id             = Column(Integer, ForeignKey("clients.id"), nullable=False)
    computed_at           = Column(DateTime, default=datetime.utcnow)
    stock_overlap_json    = Column(Text)
    sector_overlap_json   = Column(Text)
    redundancy_flags_json = Column(Text)


# -- Table 10: Pending investor chat preferences ------------------------------
class PendingPreference(Base):
    __tablename__ = "pending_preferences"

    id                 = Column(Integer, primary_key=True, index=True)
    client_id          = Column(Integer, ForeignKey("clients.id"), nullable=False)
    preference_summary = Column(Text)
    session_id         = Column(String)
    status             = Column(String, default="pending")
    advisor_id         = Column(Integer, nullable=True)
    created_at         = Column(DateTime, default=datetime.utcnow)


# -- Table 11: Agent run observability log ------------------------------------
class AgentRun(Base):
    __tablename__ = "agent_runs"

    run_id          = Column(String, primary_key=True)
    agent_name      = Column(String, nullable=False)
    trigger_type    = Column(String)
    client_id       = Column(Integer, nullable=True)
    inputs_summary  = Column(Text)
    decision_made   = Column(Text)
    action_taken    = Column(Text)
    approval_status = Column(String, default="not_required")
    approver_id     = Column(Integer, nullable=True)
    status          = Column(String, default="complete")
    failure_reason  = Column(Text, nullable=True)
    timestamp       = Column(DateTime, default=datetime.utcnow)


# -- Table 12: Report archive -------------------------------------------------
class Report(Base):
    __tablename__ = "reports"

    id              = Column(Integer, primary_key=True, index=True)
    client_id       = Column(Integer, ForeignKey("clients.id"), nullable=False)
    advisor_id      = Column(Integer, nullable=True)
    report_type     = Column(String)
    period          = Column(String)
    file_path       = Column(String)
    sent_at         = Column(DateTime, nullable=True)
    approval_status = Column(String, default="draft")
    created_at      = Column(DateTime, default=datetime.utcnow)


# -- Table 13: Transaction execution placeholder ------------------------------
class Order(Base):
    __tablename__ = "orders"

    id          = Column(Integer, primary_key=True, index=True)
    client_id   = Column(Integer, ForeignKey("clients.id"), nullable=False)
    scheme_code = Column(Integer, nullable=True)
    order_type  = Column(String)
    amount      = Column(Float)
    status      = Column(String, default="placeholder")
    placed_at   = Column(DateTime, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


# -- Table 14: Users ----------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    email         = Column(String, unique=True, index=True, nullable=False)
    phone         = Column(String)
    role          = Column(String, default="investor")
    otp_hash      = Column(String)
    otp_issued_at = Column(String)   # ISO datetime string — added Phase 6
    created_at    = Column(DateTime, default=datetime.utcnow)


# -- Table 15: Advisor-client relationships -----------------------------------
class AdvisorClient(Base):
    __tablename__ = "advisor_clients"

    id          = Column(Integer, primary_key=True, index=True)
    advisor_id  = Column(Integer, ForeignKey("users.id"), nullable=False)
    client_id   = Column(Integer, ForeignKey("clients.id"), nullable=False)
    assigned_at = Column(DateTime, default=datetime.utcnow)
    status      = Column(String, default="active")

    __table_args__ = (UniqueConstraint("advisor_id", "client_id"),)


# -- Table 16: Audit log — immutable compliance trail (Phase 6) ---------------
class AuditLog(Base):
    __tablename__ = "audit_log"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, nullable=False)
    action_type = Column(String, nullable=False)  # risk_override / report_dispatch / etc.
    entity_type = Column(String, nullable=False)  # client / goal / report / holding
    entity_id   = Column(Integer, nullable=False)
    old_value   = Column(Text)
    new_value   = Column(Text)
    reason      = Column(Text, nullable=False)    # mandatory — never blank
    timestamp   = Column(String, nullable=False)  # ISO datetime string


# -- Safe ALTER TABLE migrations for existing databases -----------------------
_MIGRATIONS = [
    ("clients",         "email",          "TEXT"),
    ("clients",         "phone",          "TEXT"),
    ("clients",         "monthly_income", "REAL"),
    ("clients",         "dependants",     "INTEGER DEFAULT 0"),
    ("clients",         "pan",            "TEXT"),
    ("clients",         "risk_profile",   "TEXT"),
    ("clients",         "updated_at",     "TEXT"),
    ("client_goals",    "goal_type",      "TEXT"),
    ("client_goals",    "current_savings","REAL DEFAULT 0"),
    ("client_holdings", "isin",           "TEXT"),
    ("client_holdings", "scheme_name",    "TEXT"),
    ("client_holdings", "purchase_date",  "TEXT"),
    ("client_holdings", "purchase_cost",  "REAL"),
    ("client_holdings", "units_bought",   "REAL"),
    # Phase 6 additions
    ("users",           "otp_issued_at",  "TEXT"),
]


def _run_migrations():
    """Add missing columns to existing SQLite databases without data loss."""
    db_file = str(DB_PATH)
    try:
        conn = sqlite3.connect(db_file)
        for table, col, defn in _MIGRATIONS:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
                logger.info("Migration: added %s.%s", table, col)
            except sqlite3.OperationalError:
                pass  # column already exists — safe to skip
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("Migration skipped (DB may not exist yet): %s", exc)


def init_db():
    """Create all tables if they don't exist, then apply safe column migrations."""
    DATA_DIR = DB_PATH.parent
    DATA_DIR.mkdir(exist_ok=True)
    Base.metadata.create_all(bind=engine)
    _run_migrations()
    print(f"Database initialised at {DB_PATH}")


if __name__ == "__main__":
    init_db()
