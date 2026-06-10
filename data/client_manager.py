"""
data/client_manager.py
-----------------------
Client data access layer for the AI Financial Advisory Tool.

Responsibilities:
  - CRUD for clients
  - CRUD for client_goals
  - CRUD for client_holdings
  - All operations use exact column names from the Phase 1 schema

Schema (as built in Phase 1):
  clients         — id, name, age, annual_income, monthly_expense, retirement_age,
                    risk_score, risk_label, created_at, email, phone, monthly_income,
                    dependants, pan, risk_profile, updated_at
  client_goals    — id, client_id, goal_name, target_amount, target_year,
                    monthly_sip, priority, risk_override
  client_holdings — id, client_id, scheme_code, goal_id, units, avg_nav, invested_amount
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from config.settings import DATABASE_PATH


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Client:
    id:               int
    name:             str
    email:            str
    phone:            str
    age:              int
    annual_income:    float
    monthly_income:   float
    dependants:       int
    pan:              Optional[str]
    risk_profile:     Optional[str]   # maps to risk_profile column
    risk_score:       Optional[float] # maps to risk_score column
    created_at:       str
    updated_at:       str


@dataclass
class ClientGoal:
    id:             int
    client_id:      int
    goal_name:      str
    target_amount:  float
    target_year:    int
    monthly_sip:    Optional[float]
    priority:       str             # VARCHAR in schema
    risk_override:  Optional[str]

@dataclass
class ClientHolding:
    id:               int
    client_id:        int
    scheme_code:      int
    goal_id:          Optional[int]
    units:            float
    avg_nav:          float
    invested_amount:  float
    current_value:    Optional[float] = None   # not in DB yet; held in memory only


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Client CRUD
# ---------------------------------------------------------------------------

def create_client(
    name: str,
    email: str,
    phone: str,
    age: int,
    annual_income: float,
    dependants: int = 0,
    pan: Optional[str] = None,
) -> Client:
    monthly_income = round(annual_income / 12, 2)
    now = datetime.utcnow().isoformat()

    with _get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO clients
                (name, email, phone, age, annual_income, monthly_income,
                 dependants, pan, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, email, phone, age, annual_income, monthly_income,
             dependants, pan, now, now),
        )
        client_id = cursor.lastrowid

    return get_client_by_id(client_id)


def get_client_by_id(client_id: int) -> Optional[Client]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
    return _row_to_client(row) if row else None


def get_client_by_email(email: str) -> Optional[Client]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM clients WHERE email = ?", (email,)
        ).fetchone()
    return _row_to_client(row) if row else None


def list_clients() -> list[Client]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM clients ORDER BY name"
        ).fetchall()
    return [_row_to_client(r) for r in rows]


def update_client_risk_profile(
    client_id: int,
    risk_profile: str,
    risk_score: float,
) -> bool:
    now = datetime.utcnow().isoformat()
    with _get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE clients
            SET risk_profile = ?, risk_score = ?, updated_at = ?
            WHERE id = ?
            """,
            (risk_profile, risk_score, now, client_id),
        )
    return cursor.rowcount > 0


def update_client(
    client_id: int,
    name: Optional[str] = None,
    phone: Optional[str] = None,
    age: Optional[int] = None,
    annual_income: Optional[float] = None,
    dependants: Optional[int] = None,
    pan: Optional[str] = None,
) -> bool:
    fields, values = [], []
    if name          is not None: fields.append("name = ?");          values.append(name)
    if phone         is not None: fields.append("phone = ?");         values.append(phone)
    if age           is not None: fields.append("age = ?");           values.append(age)
    if dependants    is not None: fields.append("dependants = ?");    values.append(dependants)
    if pan           is not None: fields.append("pan = ?");           values.append(pan)
    if annual_income is not None:
        fields.append("annual_income = ?");  values.append(annual_income)
        fields.append("monthly_income = ?"); values.append(round(annual_income / 12, 2))

    if not fields:
        return False

    now = datetime.utcnow().isoformat()
    fields.append("updated_at = ?"); values.append(now)
    values.append(client_id)

    with _get_conn() as conn:
        cursor = conn.execute(
            f"UPDATE clients SET {', '.join(fields)} WHERE id = ?", values
        )
    return cursor.rowcount > 0


def delete_client(client_id: int) -> bool:
    with _get_conn() as conn:
        conn.execute("DELETE FROM client_holdings WHERE client_id = ?", (client_id,))
        conn.execute("DELETE FROM client_goals WHERE client_id = ?", (client_id,))
        cursor = conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Client Goals CRUD
# ---------------------------------------------------------------------------

def add_goal(
    client_id: int,
    goal_name: str,
    target_amount: float,
    target_year: int,
    monthly_sip: Optional[float] = None,
    priority: str = "1",
    risk_override: Optional[str] = None,
    # accepted but ignored — kept so callers don't break
    goal_type: Optional[str] = None,
    current_savings: Optional[float] = None,
) -> ClientGoal:
    with _get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO client_goals
                (client_id, goal_name, target_amount, target_year,
                 monthly_sip, priority, risk_override)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (client_id, goal_name, target_amount, target_year,
             monthly_sip, str(priority), risk_override),
        )
        goal_id = cursor.lastrowid
    return get_goal_by_id(goal_id)


def get_goal_by_id(goal_id: int) -> Optional[ClientGoal]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM client_goals WHERE id = ?", (goal_id,)
        ).fetchone()
    return _row_to_goal(row) if row else None


def get_goals_for_client(client_id: int) -> list[ClientGoal]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM client_goals WHERE client_id = ? ORDER BY priority, target_year",
            (client_id,),
        ).fetchall()
    return [_row_to_goal(r) for r in rows]


def update_goal_sip(goal_id: int, monthly_sip: float) -> bool:
    with _get_conn() as conn:
        cursor = conn.execute(
            "UPDATE client_goals SET monthly_sip = ? WHERE id = ?",
            (monthly_sip, goal_id),
        )
    return cursor.rowcount > 0


def delete_goal(goal_id: int) -> bool:
    with _get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM client_goals WHERE id = ?", (goal_id,)
        )
    return cursor.rowcount > 0

def deactivate_goal(goal_id: int) -> bool:
    """No is_active column in schema — falls back to hard delete."""
    return delete_goal(goal_id)


# ---------------------------------------------------------------------------
# Client Holdings CRUD
# ---------------------------------------------------------------------------

def add_holding(
    client_id: int,
    scheme_code: int,
    units: float,
    avg_nav: float,
    invested_amount: float,
    goal_id: Optional[int] = None,
    # accepted but ignored — kept so callers don't break
    scheme_name: Optional[str] = None,
    current_value: Optional[float] = None,
    as_of_date: Optional[str] = None,
) -> ClientHolding:
    with _get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO client_holdings
                (client_id, scheme_code, goal_id, units, avg_nav, invested_amount)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (client_id, scheme_code, goal_id, units, avg_nav, invested_amount),
        )
        holding_id = cursor.lastrowid
    return get_holding_by_id(holding_id)


def get_holding_by_id(holding_id: int) -> Optional[ClientHolding]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM client_holdings WHERE id = ?", (holding_id,)
        ).fetchone()
    return _row_to_holding(row) if row else None


def get_holdings_for_client(client_id: int) -> list[ClientHolding]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM client_holdings WHERE client_id = ? ORDER BY invested_amount DESC",
            (client_id,),
        ).fetchall()
    return [_row_to_holding(r) for r in rows]


def delete_holding(holding_id: int) -> bool:
    with _get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM client_holdings WHERE id = ?", (holding_id,)
        )
    return cursor.rowcount > 0

def update_holding_current_value(holding_id: int, current_value: float) -> bool:
    """No current_value column in schema — no-op until Phase 3 NAV refresh adds it."""
    return True

def get_portfolio_summary(client_id: int) -> dict:
    holdings = get_holdings_for_client(client_id)
    total_invested = sum(h.invested_amount for h in holdings)
    # No current_value column — use invested_amount as proxy until NAV refresh runs
    return {
        "total_invested":  total_invested,
        "total_current":   total_invested,   # updated by nav_fetcher in Phase 3
        "absolute_gain":   0.0,
        "gain_percentage": 0.0,
        "num_holdings":    len(holdings),
    }


# ---------------------------------------------------------------------------
# Row → dataclass converters
# ---------------------------------------------------------------------------

def _row_to_client(row: sqlite3.Row) -> Client:
    d = dict(row)
    return Client(
        id=d["id"],
        name=d["name"],
        email=d.get("email", ""),
        phone=d.get("phone", ""),
        age=d["age"],
        annual_income=d["annual_income"],
        monthly_income=d.get("monthly_income") or round(d["annual_income"] / 12, 2),
        dependants=d.get("dependants") or 0,
        pan=d.get("pan"),
        risk_profile=d.get("risk_profile"),
        risk_score=d.get("risk_score"),
        created_at=d.get("created_at", ""),
        updated_at=d.get("updated_at", ""),
    )


def _row_to_goal(row: sqlite3.Row) -> ClientGoal:
    d = dict(row)
    return ClientGoal(
        id=d["id"],
        client_id=d["client_id"],
        goal_name=d["goal_name"],
        target_amount=d["target_amount"],
        target_year=d["target_year"],
        monthly_sip=d.get("monthly_sip"),
        priority=d.get("priority", "1"),
        risk_override=d.get("risk_override"),
    )

def _row_to_holding(row: sqlite3.Row) -> ClientHolding:
    d = dict(row)
    return ClientHolding(
        id=d["id"],
        client_id=d["client_id"],
        scheme_code=d["scheme_code"],
        goal_id=d.get("goal_id"),
        units=d["units"],
        avg_nav=d["avg_nav"],
        invested_amount=d["invested_amount"],
        current_value=None,   # populated by update_holding_current_value in memory
    )
