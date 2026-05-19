from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import text

from utils.notifications import send_email_notification


ENTITY_TABLES = {
    "document": {
        "table": "documents",
        "id_column": "doc_id",
        "name_column": "document_name",
    },
    "submission": {
        "table": "submissions",
        "id_column": "submission_id",
        "name_column": "submission_type",
    },
}

CONFIG_TABLES = {
    "product_types": {
        "id_column": "product_type_id",
        "name_column": "name",
    },
    "submission_types": {
        "id_column": "submission_type_id",
        "name_column": "name",
    },
    "countries": {
        "id_column": "country_id",
        "name_column": "country_name",
    },
}


def ensure_compliance_features(engine):
    """Create audit/approval tables and migrate approval columns."""
    with engine.connect() as conn:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS audit_trail (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            user_role TEXT,
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id INTEGER,
            details TEXT,
            created_at TEXT NOT NULL
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS approval_workflow (
            approval_id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            requested_by INTEGER,
            requested_by_name TEXT,
            requested_at TEXT,
            status TEXT NOT NULL,
            reviewed_by INTEGER,
            reviewed_by_name TEXT,
            reviewed_at TEXT,
            decision_notes TEXT
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS alerts (
            alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_key TEXT UNIQUE,
            product_id INTEGER,
            product_name TEXT,
            alert_type TEXT,
            severity TEXT,
            message TEXT,
            details TEXT,
            action TEXT,
            status TEXT DEFAULT 'Open',
            assigned_to INTEGER,
            due_date TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS alert_subscriptions (
            subscription_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            alert_type TEXT,
            is_active INTEGER DEFAULT 1
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS product_types (
            product_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS submission_types (
            submission_type_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS countries (
            country_id INTEGER PRIMARY KEY AUTOINCREMENT,
            country_name TEXT UNIQUE NOT NULL,
            region TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS document_requirements (
            requirement_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_type TEXT NOT NULL,
            country TEXT,
            submission_type TEXT,
            document_type TEXT NOT NULL,
            required INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS sop_policies (
            policy_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
        """))

        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS policy_steps (
            step_id INTEGER PRIMARY KEY AUTOINCREMENT,
            policy_id INTEGER NOT NULL,
            step_order INTEGER DEFAULT 0,
            title TEXT NOT NULL,
            role TEXT,
            due_days INTEGER DEFAULT 0,
            instructions TEXT
        )
        """))

        conn.execute(text("""
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
        """))

        migrations = {
            "documents": {
                "extracted_text": "TEXT",
                "extraction_status": "TEXT",
                "extraction_pages": "INTEGER",
                "approval_status": "TEXT DEFAULT 'Draft'",
                "approval_requested_by": "TEXT",
                "approval_requested_at": "TEXT",
                "approved_by": "TEXT",
                "approved_at": "TEXT",
            },
            "submissions": {
                "approval_status": "TEXT DEFAULT 'Draft'",
                "approval_requested_by": "TEXT",
                "approval_requested_at": "TEXT",
                "approved_by": "TEXT",
                "approved_at": "TEXT",
            },
        }

        for table_name, columns in migrations.items():
            existing_columns = {
                row[1]
                for row in conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            }
            for column_name, column_type in columns.items():
                if column_name not in existing_columns:
                    conn.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
                    )

        conn.commit()


def log_audit_event(engine, user, action, entity_type=None, entity_id=None, details=""):
    """Persist an audit event. Failures should not break the user workflow."""
    try:
        user = user or {}
        with engine.connect() as conn:
            conn.execute(
                text("""
                INSERT INTO audit_trail (
                    user_id, username, user_role, action, entity_type,
                    entity_id, details, created_at
                )
                VALUES (
                    :user_id, :username, :user_role, :action, :entity_type,
                    :entity_id, :details, :created_at
                )
                """),
                {
                    "user_id": user.get("user_id"),
                    "username": user.get("username"),
                    "user_role": user.get("role"),
                    "action": action,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "details": details,
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                },
            )
            conn.commit()
    except Exception:
        return False
    return True


def _get_entity_config(entity_type):
    if entity_type not in ENTITY_TABLES:
        raise ValueError("Unsupported approval entity type")
    return ENTITY_TABLES[entity_type]


def request_approval(engine, user, entity_type, entity_id):
    config = _get_entity_config(entity_type)
    now = datetime.now().isoformat(timespec="seconds")
    with engine.connect() as conn:
        conn.execute(
            text(f"""
            UPDATE {config["table"]}
            SET approval_status = 'Pending Review',
                approval_requested_by = :requested_by,
                approval_requested_at = :requested_at
            WHERE {config["id_column"]} = :entity_id
            """),
            {
                "requested_by": user.get("username"),
                "requested_at": now,
                "entity_id": entity_id,
            },
        )
        conn.execute(
            text("""
            INSERT INTO approval_workflow (
                entity_type, entity_id, requested_by, requested_by_name,
                requested_at, status
            )
            VALUES (
                :entity_type, :entity_id, :requested_by, :requested_by_name,
                :requested_at, 'Pending Review'
            )
            """),
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "requested_by": user.get("user_id"),
                "requested_by_name": user.get("username"),
                "requested_at": now,
            },
        )
        conn.commit()

    log_audit_event(
        engine,
        user,
        "APPROVAL_REQUESTED",
        entity_type,
        entity_id,
        "Approval requested",
    )


def complete_approval(engine, user, entity_type, entity_id, decision, notes=""):
    if decision not in {"Approved", "Rejected"}:
        raise ValueError("Decision must be Approved or Rejected")

    config = _get_entity_config(entity_type)
    now = datetime.now().isoformat(timespec="seconds")
    with engine.connect() as conn:
        conn.execute(
            text(f"""
            UPDATE {config["table"]}
            SET approval_status = :approval_status,
                approved_by = :approved_by,
                approved_at = :approved_at
            WHERE {config["id_column"]} = :entity_id
            """),
            {
                "approval_status": decision,
                "approved_by": user.get("username"),
                "approved_at": now,
                "entity_id": entity_id,
            },
        )
        conn.execute(
            text("""
            UPDATE approval_workflow
            SET status = :status,
                reviewed_by = :reviewed_by,
                reviewed_by_name = :reviewed_by_name,
                reviewed_at = :reviewed_at,
                decision_notes = :decision_notes
            WHERE approval_id = (
                SELECT approval_id
                FROM approval_workflow
                WHERE entity_type = :entity_type
                  AND entity_id = :entity_id
                  AND status = 'Pending Review'
                ORDER BY approval_id DESC
                LIMIT 1
            )
            """),
            {
                "status": decision,
                "reviewed_by": user.get("user_id"),
                "reviewed_by_name": user.get("username"),
                "reviewed_at": now,
                "decision_notes": notes,
                "entity_type": entity_type,
                "entity_id": entity_id,
            },
        )
        conn.commit()

    log_audit_event(
        engine,
        user,
        f"APPROVAL_{decision.upper()}",
        entity_type,
        entity_id,
        notes or f"{entity_type.title()} {decision.lower()}",
    )


def get_audit_trail(engine, limit=250):
    with engine.connect() as conn:
        return pd.read_sql(
            text("""
            SELECT
                audit_id,
                created_at,
                username,
                user_role,
                action,
                entity_type,
                entity_id,
                details
            FROM audit_trail
            ORDER BY audit_id DESC
            LIMIT :limit
            """),
            conn,
            params={"limit": limit},
        )


def get_approval_history(engine, limit=250):
    with engine.connect() as conn:
        return pd.read_sql(
            text("""
            SELECT
                approval_id,
                entity_type,
                entity_id,
                requested_by_name,
                requested_at,
                status,
                reviewed_by_name,
                reviewed_at,
                decision_notes
            FROM approval_workflow
            ORDER BY approval_id DESC
            LIMIT :limit
            """),
            conn,
            params={"limit": limit},
        )


def create_alert(
    engine,
    product_id,
    product_name,
    alert_type,
    severity,
    message,
    details,
    action,
    due_date=None,
    assigned_to=None,
):
    alert_key = f"{product_id}:{alert_type}:{message}"
    now = datetime.now().isoformat(timespec="seconds")
    with engine.connect() as conn:
        conn.execute(
            text("""
            INSERT OR IGNORE INTO alerts (
                alert_key, product_id, product_name, alert_type, severity,
                message, details, action, status, assigned_to, due_date,
                created_at, updated_at
            ) VALUES (
                :alert_key, :product_id, :product_name, :alert_type, :severity,
                :message, :details, :action, 'Open', :assigned_to, :due_date,
                :created_at, :updated_at
            )
            """),
            {
                "alert_key": alert_key,
                "product_id": product_id,
                "product_name": product_name,
                "alert_type": alert_type,
                "severity": severity,
                "message": message,
                "details": details,
                "action": action,
                "assigned_to": assigned_to,
                "due_date": due_date,
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.execute(
            text("""
            UPDATE alerts
            SET severity = :severity,
                details = :details,
                action = :action,
                updated_at = :updated_at
            WHERE alert_key = :alert_key
            """),
            {
                "alert_key": alert_key,
                "severity": severity,
                "details": details,
                "action": action,
                "updated_at": now,
            },
        )
        conn.commit()


def update_alert_status(engine, alert_id, status, comments=""):
    now = datetime.now().isoformat(timespec="seconds")
    with engine.connect() as conn:
        conn.execute(
            text("""
            UPDATE alerts
            SET status = :status,
                details = CASE WHEN :comments != '' THEN details || '
' || :comments ELSE details END,
                updated_at = :updated_at
            WHERE alert_id = :alert_id
            """),
            {
                "status": status,
                "comments": comments,
                "updated_at": now,
                "alert_id": alert_id,
            },
        )
        conn.commit()


def _get_user_email(engine, user_id):
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT email FROM users WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).fetchone()
        return row[0] if row else None


def assign_alert(engine, alert_id, user_id):
    now = datetime.now().isoformat(timespec="seconds")
    with engine.connect() as conn:
        conn.execute(
            text("""
            UPDATE alerts
            SET assigned_to = :assigned_to,
                updated_at = :updated_at
            WHERE alert_id = :alert_id
            """),
            {
                "assigned_to": user_id,
                "updated_at": now,
                "alert_id": alert_id,
            },
        )
        alert_row = conn.execute(
            text("SELECT * FROM alerts WHERE alert_id = :alert_id"),
            {"alert_id": alert_id},
        ).fetchone()
        conn.commit()

    email = _get_user_email(engine, user_id)
    if email and alert_row:
        subject = f"Alert assigned: {alert_row['alert_type']}"
        body = (
            f"You have been assigned an alert for product {alert_row['product_name']}.\n\n"
            f"Alert: {alert_row['alert_type']}\n"
            f"Severity: {alert_row['severity']}\n"
            f"Message: {alert_row['message']}\n"
            f"Details: {alert_row['details']}\n"
            f"Action: {alert_row['action']}\n"
        )
        send_email_notification(email, subject, body)


def get_alerts(engine, status=None):
    with engine.connect() as conn:
        if status:
            return pd.read_sql(
                text("""
                SELECT *
                FROM alerts
                WHERE status = :status
                ORDER BY created_at DESC
                """),
                conn,
                params={"status": status},
            )

        return pd.read_sql(
            text("""
            SELECT *
            FROM alerts
            ORDER BY created_at DESC
            """),
            conn,
        )


def get_alert_subscribers(engine, alert_type=None):
    with engine.connect() as conn:
        if alert_type:
            return pd.read_sql(
                text("""
                SELECT u.user_id, u.username, u.email
                FROM users u
                JOIN alert_subscriptions s
                ON u.user_id = s.user_id
                WHERE s.is_active = 1
                  AND (s.alert_type = :alert_type OR s.alert_type IS NULL OR s.alert_type = '')
                """),
                conn,
                params={"alert_type": alert_type},
            )

        return pd.read_sql(
            text("""
            SELECT u.user_id, u.username, u.email
            FROM users u
            JOIN alert_subscriptions s
            ON u.user_id = s.user_id
            WHERE s.is_active = 1
            """),
            conn,
        )


def _validate_config_table(table_name):
    if table_name not in CONFIG_TABLES:
        raise ValueError(f"Unsupported config table: {table_name}")


def get_reference_items(engine, table_name, active_only=True):
    _validate_config_table(table_name)
    config = CONFIG_TABLES[table_name]
    query = f"SELECT * FROM {table_name}"
    if active_only:
        query += " WHERE is_active = 1"
    query += f" ORDER BY {config['name_column']}"
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn)


def save_reference_item(engine, table_name, name, description="", is_active=1, item_id=None):
    _validate_config_table(table_name)
    config = CONFIG_TABLES[table_name]
    now = datetime.now().isoformat(timespec="seconds")
    if item_id:
        with engine.connect() as conn:
            conn.execute(
                text(
                    f"UPDATE {table_name} SET {config['name_column']} = :name, description = :description, is_active = :is_active, updated_at = :updated_at WHERE {config['id_column']} = :item_id"
                ),
                {
                    "name": name,
                    "description": description,
                    "is_active": is_active,
                    "updated_at": now,
                    "item_id": item_id,
                },
            )
            conn.commit()
    else:
        with engine.connect() as conn:
            conn.execute(
                text(
                    f"INSERT OR IGNORE INTO {table_name} ({config['name_column']}, description, is_active, created_at, updated_at) VALUES (:name, :description, :is_active, :created_at, :updated_at)"
                ),
                {
                    "name": name,
                    "description": description,
                    "is_active": is_active,
                    "created_at": now,
                    "updated_at": now,
                },
            )
            conn.commit()


def delete_reference_item(engine, table_name, item_id):
    _validate_config_table(table_name)
    with engine.connect() as conn:
        conn.execute(
            text(f"DELETE FROM {table_name} WHERE {CONFIG_TABLES[table_name]['id_column']} = :item_id"),
            {"item_id": item_id},
        )
        conn.commit()


def get_pending_approvals(engine, limit=100):
    with engine.connect() as conn:
        return pd.read_sql(
            text("""
            SELECT
                approval_id,
                entity_type,
                entity_id,
                requested_by_name,
                requested_at,
                status,
                decision_notes
            FROM approval_workflow
            WHERE status = 'Pending Review'
            ORDER BY requested_at DESC
            LIMIT :limit
            """),
            conn,
            params={"limit": limit},
        )


def escalate_stale_alerts(engine, days_threshold=7):
    threshold = datetime.now() - timedelta(days=days_threshold)
    escalated_alerts = []

    with engine.connect() as conn:
        open_alerts = conn.execute(
            text("SELECT * FROM alerts WHERE status = 'Open'")
        ).fetchall()

    for row in open_alerts:
        created_at = row['created_at']
        try:
            created_at_dt = datetime.fromisoformat(created_at)
        except Exception:
            continue

        if created_at_dt <= threshold:
            new_severity = 'Critical' if row['severity'] == 'High' else row['severity']
            updated_details = (
                f"{row['details']}\n\nEscalated after {days_threshold} days open."
            )
            now = datetime.now().isoformat(timespec="seconds")
            with engine.connect() as conn:
                conn.execute(
                    text("""
                    UPDATE alerts
                    SET status = 'In Progress',
                        severity = :severity,
                        details = :details,
                        updated_at = :updated_at
                    WHERE alert_id = :alert_id
                    """),
                    {
                        "severity": new_severity,
                        "details": updated_details,
                        "updated_at": now,
                        "alert_id": row['alert_id'],
                    },
                )
                conn.commit()

            escalated_alerts.append(row['alert_id'])

            if row['assigned_to']:
                email = _get_user_email(engine, row['assigned_to'])
                if email:
                    subject = f"Escalated alert: {row['alert_type']}"
                    body = (
                        f"The alert for product {row['product_name']} has been escalated.\n\n"
                        f"Message: {row['message']}\n"
                        f"Details: {updated_details}\n"
                        f"Action: {row['action']}\n"
                    )
                    send_email_notification(email, subject, body)
            else:
                subscribers = get_alert_subscribers(engine, row['alert_type'])
                for _, subscriber in subscribers.iterrows():
                    if subscriber['email']:
                        subject = f"Escalated alert: {row['alert_type']}"
                        body = (
                            f"The alert for product {row['product_name']} has been escalated.\n\n"
                            f"Message: {row['message']}\n"
                            f"Details: {updated_details}\n"
                            f"Action: {row['action']}\n"
                        )
                        send_email_notification(subscriber['email'], subject, body)

    return len(escalated_alerts)
