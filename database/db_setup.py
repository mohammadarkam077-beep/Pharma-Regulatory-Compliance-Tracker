import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[1]))

from utils.database import get_engine
from utils.compliance_workflow import ensure_compliance_features

# Create SQLite database
engine = get_engine()

with engine.connect() as conn:

    # Products table
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS products (
        product_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT,
        dosage_form TEXT,
        strength TEXT,
        country TEXT,
        registration_no TEXT,
        product_type TEXT CHECK(product_type IN (
            'Pharmaceutical',
            'Medical Device',
            'Biologics',
            'Combination Product',
            'Other'
        ))
    )
    """))

    # Reference metadata tables for product, country and submission configuration
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

    now = datetime.now().isoformat(timespec='seconds')
    conn.execute(text("""
    INSERT OR IGNORE INTO product_types (name, description, created_at, updated_at)
    VALUES
        ('Pharmaceutical', 'Small molecule drugs and formulations.', :now, :now),
        ('Medical Device', 'Device products requiring regulatory clearance.', :now, :now),
        ('Biologics', 'Biotech and biological therapeutic products.', :now, :now),
        ('Combination Product', 'Products combining drug and device elements.', :now, :now),
        ('Other', 'Other regulated product categories.', :now, :now)
    """), {"now": now})

    conn.execute(text("""
    INSERT OR IGNORE INTO submission_types (name, description, created_at, updated_at)
    VALUES
        ('New Registration', 'Initial registration filing.', :now, :now),
        ('Renewal', 'License or registration renewal.', :now, :now),
        ('Variation', 'Change request for an existing registration.', :now, :now),
        ('Re-Registration', 'Re-submission of a registration dossier.', :now, :now),
        ('Amendment', 'Minor amendment to an existing filing.', :now, :now),
        ('Clinical Trial Application', 'Clinical trial authorization filing.', :now, :now),
        ('Import License', 'Import license application.', :now, :now),
        ('Registration Transfer', 'Transfer of registration ownership.', :now, :now)
    """), {"now": now})

    conn.execute(text("""
    INSERT OR IGNORE INTO countries (country_name, region, created_at, updated_at)
    VALUES
        ('India', 'Asia', :now, :now),
        ('USA', 'Americas', :now, :now),
        ('Germany', 'Europe', :now, :now),
        ('Brazil', 'Americas', :now, :now),
        ('Japan', 'Asia', :now, :now)
    """), {"now": now})

    # Submissions table
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS submissions (
        submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        submission_type TEXT,
        submission_status TEXT,
        submission_date TEXT,
        renewal_due_date TEXT
    )
    """))

    # Documents table
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS documents (
        doc_id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        document_name TEXT,
        document_type TEXT,
        version TEXT,
        upload_date TEXT,
        file_path TEXT,
        extracted_text TEXT,
        extraction_status TEXT,
        extraction_pages INTEGER
    )
    """))

    # Document requirement rules
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

    # Alerts table for persisted workflow
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

    # Alert subscriptions for email notifications
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS alert_subscriptions (
        subscription_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        alert_type TEXT,
        is_active INTEGER DEFAULT 1
    )
    """))

    existing_columns = {
        row[1]
        for row in conn.execute(text("PRAGMA table_info(documents)")).fetchall()
    }
    document_columns = {
        "extracted_text": "TEXT",
        "extraction_status": "TEXT",
        "extraction_pages": "INTEGER",
    }
    for column_name, column_type in document_columns.items():
        if column_name not in existing_columns:
            conn.execute(
                text(f"ALTER TABLE documents ADD COLUMN {column_name} {column_type}")
            )

    existing_product_columns = {
        row[1]
        for row in conn.execute(text("PRAGMA table_info(products)")).fetchall()
    }
    if "product_type" not in existing_product_columns:
        conn.execute(text("ALTER TABLE products ADD COLUMN product_type TEXT"))

    # Users table for role-based access
    conn.execute(text("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        email TEXT UNIQUE,
        role TEXT NOT NULL,
        full_name TEXT,
        created_at TEXT,
        last_login TEXT,
        is_active BOOLEAN DEFAULT 1
    )
    """))

    conn.commit()

ensure_compliance_features(engine)

print("Database and tables created successfully.")
