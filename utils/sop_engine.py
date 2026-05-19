from datetime import datetime, timedelta
from sqlalchemy import text
import pandas as pd


def normalize_text(value):
    return str(value or "").strip().lower()


def ensure_sop_tables(engine):
    with engine.connect() as conn:
        conn.execute(text('''
        CREATE TABLE IF NOT EXISTS sop_policies (
            policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            product_type TEXT,
            country TEXT,
            submission_type TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
        '''))

        conn.execute(text('''
        CREATE TABLE IF NOT EXISTS policy_steps (
            step_id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_id INTEGER NOT NULL,
            step_order INTEGER DEFAULT 0,
            title TEXT NOT NULL,
            role TEXT,
            due_days INTEGER DEFAULT 0,
            instructions TEXT
        )
        '''))

        conn.execute(text('''
        CREATE TABLE IF NOT EXISTS policy_assignments (
            assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_id INTEGER,
            submission_id INTEGER,
            product_id INTEGER,
            step_id INTEGER,
            assigned_to INTEGER,
            status TEXT DEFAULT 'Open',
            due_date TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        '''))
        conn.commit()


def create_policy(engine, name, description="", product_type=None, country=None, submission_type=None):
    now = datetime.now().isoformat(timespec="seconds")
    with engine.connect() as conn:
        conn.execute(
            text("INSERT OR IGNORE INTO sop_policies (name, description, product_type, country, submission_type, created_at, updated_at) VALUES (:name, :description, :product_type, :country, :submission_type, :created_at, :updated_at)"),
            {
                "name": name,
                "description": description,
                "product_type": product_type,
                "country": country,
                "submission_type": submission_type,
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.commit()


def add_policy_step(engine, policy_id, step_order, title, role=None, due_days=0, instructions=None):
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO policy_steps (policy_id, step_order, title, role, due_days, instructions) VALUES (:policy_id, :step_order, :title, :role, :due_days, :instructions)"),
            {
                "policy_id": policy_id,
                "step_order": step_order,
                "title": title,
                "role": role,
                "due_days": due_days,
                "instructions": instructions,
            },
        )
        conn.commit()


def get_policies(engine, active_only=True):
    q = "SELECT * FROM sop_policies"
    if active_only:
        q += " WHERE is_active = 1"
    with engine.connect() as conn:
        return pd.read_sql(text(q), conn)


def get_matching_policies(engine, product_type=None, country=None, submission_type=None):
    product_type_key = normalize_text(product_type)
    country_key = normalize_text(country)
    submission_key = normalize_text(submission_type)

    with engine.connect() as conn:
        return pd.read_sql(
            text("""
            SELECT *
            FROM sop_policies
            WHERE is_active = 1
              AND (
                    lower(product_type) = :product_type
                    OR product_type IS NULL
                    OR product_type = ''
                  )
              AND (
                    lower(country) = :country
                    OR country IS NULL
                    OR country = ''
                  )
              AND (
                    lower(submission_type) = :submission_type
                    OR submission_type IS NULL
                    OR submission_type = ''
                  )
            """),
            conn,
            params={
                "product_type": product_type_key,
                "country": country_key,
                "submission_type": submission_key,
            },
        )


def get_policy_steps(engine, policy_id):
    with engine.connect() as conn:
        return pd.read_sql(
            text("SELECT * FROM policy_steps WHERE policy_id = :policy_id ORDER BY step_order"),
            conn,
            params={"policy_id": policy_id},
        )


def assign_policy_to_submission(engine, policy_id, submission_id, product_id=None):
    """Create policy_assignments rows for the submission based on policy steps."""
    now = datetime.now().isoformat(timespec="seconds")
    steps = get_policy_steps(engine, policy_id)
    if steps.empty:
        return 0

    created = 0
    with engine.connect() as conn:
        for _, step in steps.iterrows():
            due_date = None
            try:
                due_days = int(step.get("due_days") or 0)
                if due_days:
                    due_date = (datetime.now() + timedelta(days=due_days)).isoformat(timespec="seconds")
            except Exception:
                due_date = None

            conn.execute(
                text("INSERT INTO policy_assignments (policy_id, submission_id, product_id, step_id, assigned_to, status, due_date, created_at, updated_at) VALUES (:policy_id, :submission_id, :product_id, :step_id, NULL, 'Open', :due_date, :created_at, :updated_at)"),
                {
                    "policy_id": policy_id,
                    "submission_id": submission_id,
                    "product_id": product_id,
                    "step_id": int(step["step_id"]),
                    "due_date": due_date,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            created += 1
        conn.commit()
    return created


def get_policy_assignments(engine, submission_id=None, status=None):
    q = "SELECT pa.*, ps.title AS step_title, ps.role AS step_role, sp.name AS policy_name, p.product_name, s.submission_type"
    q += " FROM policy_assignments pa"
    q += " LEFT JOIN policy_steps ps ON pa.step_id = ps.step_id"
    q += " LEFT JOIN sop_policies sp ON pa.policy_id = sp.policy_id"
    q += " LEFT JOIN products p ON pa.product_id = p.product_id"
    q += " LEFT JOIN submissions s ON pa.submission_id = s.submission_id"
    params = {}
    clauses = []
    if submission_id:
        clauses.append("pa.submission_id = :submission_id")
        params["submission_id"] = submission_id
    if status:
        clauses.append("pa.status = :status")
        params["status"] = status
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    with engine.connect() as conn:
        return pd.read_sql(text(q + " ORDER BY pa.created_at DESC"), conn, params=params)


def get_user_assignments(engine, user_id=None, status=None, unassigned=False):
    q = "SELECT pa.*, ps.title AS step_title, ps.role AS step_role, sp.name AS policy_name, p.product_name, s.submission_type"
    q += " FROM policy_assignments pa"
    q += " LEFT JOIN policy_steps ps ON pa.step_id = ps.step_id"
    q += " LEFT JOIN sop_policies sp ON pa.policy_id = sp.policy_id"
    q += " LEFT JOIN products p ON pa.product_id = p.product_id"
    q += " LEFT JOIN submissions s ON pa.submission_id = s.submission_id"
    params = {}
    clauses = []
    if user_id is not None:
        clauses.append("pa.assigned_to = :user_id")
        params["user_id"] = user_id
    if unassigned:
        clauses.append("pa.assigned_to IS NULL")
    if status:
        clauses.append("pa.status = :status")
        params["status"] = status
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    with engine.connect() as conn:
        return pd.read_sql(text(q + " ORDER BY pa.created_at DESC"), conn, params=params)


def claim_assignment(engine, assignment_id, user_id):
    now = datetime.now().isoformat(timespec="seconds")
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE policy_assignments SET assigned_to = :user_id, updated_at = :updated_at WHERE assignment_id = :assignment_id"),
            {"user_id": user_id, "updated_at": now, "assignment_id": assignment_id},
        )
        conn.commit()
    return True


def complete_assignment(engine, assignment_id, user_id=None):
    now = datetime.now().isoformat(timespec="seconds")
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE policy_assignments SET status = 'Completed', updated_at = :updated_at WHERE assignment_id = :assignment_id"),
            {"updated_at": now, "assignment_id": assignment_id},
        )
        if user_id is not None:
            conn.execute(
                text("UPDATE policy_assignments SET assigned_to = :user_id WHERE assignment_id = :assignment_id"),
                {"user_id": user_id, "assignment_id": assignment_id},
            )
        conn.commit()
    return True


def update_assignment_status(engine, assignment_id, status, user_id=None, comments=None):
    now = datetime.now().isoformat(timespec="seconds")
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE policy_assignments SET status = :status, updated_at = :updated_at WHERE assignment_id = :assignment_id"),
            {"status": status, "updated_at": now, "assignment_id": assignment_id},
        )
        conn.commit()
    return True
