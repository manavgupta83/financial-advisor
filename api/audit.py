"""
api/audit.py
-------------
Audit and agent observability helpers.

log_audit()     -- writes an immutable row to audit_log for every override,
                   role change, report dispatch, or agent approval.
                   INSERT only -- rows are never updated or deleted.

log_agent_run() -- writes a row to agent_runs for every agent invocation.
                   Returns the UUID run_id for downstream reference.

These functions are called by routers on every override / approval event.
"""

import sqlite3
import uuid
import logging
from datetime import datetime, timezone

from config.settings import DATABASE_PATH

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audit log -- immutable compliance trail
# ---------------------------------------------------------------------------

def log_audit(
    user_id: int,
    action_type: str,
    entity_type: str,
    entity_id: int,
    old_value: str,
    new_value: str,
    reason: str,
) -> None:
    """
    Append an immutable audit record.
    Raises ValueError if reason is blank -- do not silently skip the reason.
    """
    if not reason or not reason.strip():
        raise ValueError("audit log requires a non-empty reason")

    ts = datetime.now(timezone.utc).isoformat()
    try:
        with sqlite3.connect(DATABASE_PATH) as conn:
            conn.execute(
                """INSERT INTO audit_log
                   (user_id, action_type, entity_type, entity_id,
                    old_value, new_value, reason, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, action_type, entity_type, entity_id,
                 old_value, new_value, reason, ts),
            )
        logger.info(
            "AUDIT user=%d action=%s entity=%s/%d",
            user_id, action_type, entity_type, entity_id,
        )
    except sqlite3.Error as exc:
        logger.error("audit_log INSERT failed: %s", exc)
        raise


# ---------------------------------------------------------------------------
# Agent run log
# ---------------------------------------------------------------------------

def log_agent_run(
    agent_name: str,
    trigger_type: str,
    client_id: int | None,
    inputs_summary: str,
    decision_made: str,
    action_taken: str,
    approval_status: str,
    status: str = "complete",
    failure_reason: str | None = None,
    approver_id: int | None = None,
) -> str:
    """
    Write a row to agent_runs and return the generated run_id (UUID).
    Every agent call must invoke this -- no exceptions.
    """
    run_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()

    try:
        with sqlite3.connect(DATABASE_PATH) as conn:
            conn.execute(
                """INSERT INTO agent_runs
                   (run_id, agent_name, trigger_type, client_id, inputs_summary,
                    decision_made, action_taken, approval_status, approver_id,
                    status, failure_reason, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, agent_name, trigger_type, client_id, inputs_summary,
                 decision_made, action_taken, approval_status, approver_id,
                 status, failure_reason, ts),
            )
        logger.info("AGENT_RUN run_id=%s agent=%s status=%s", run_id, agent_name, status)
    except sqlite3.Error as exc:
        logger.error("agent_runs INSERT failed: %s", exc)
        raise

    return run_id


def update_agent_run_approval(
    run_id: str,
    approval_status: str,
    approver_id: int,
) -> None:
    """Update the approval_status of an agent run. Only pending -> approved/rejected."""
    with sqlite3.connect(DATABASE_PATH) as conn:
        conn.execute(
            """UPDATE agent_runs
               SET approval_status = ?, approver_id = ?
               WHERE run_id = ? AND approval_status = 'pending'""",
            (approval_status, approver_id, run_id),
        )
