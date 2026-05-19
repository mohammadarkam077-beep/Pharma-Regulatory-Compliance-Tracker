from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import text

from utils.database import get_engine as create_app_engine
from utils.compliance_workflow import create_alert

# Document requirements by product type
REQUIRED_DOCUMENTS = {
    "pharmaceutical": [
        "CTD",
        "CTA Form",
        "Safety Report",
        "SOP - Manufacturing",
        "SOP - Quality Control",
        "COA",
        "Stability Report"
    ],
    "medical_device": [
        "Device Master Record",
        "Device History Record",
        "Risk Assessment",
        "SOP - Sterilization",
        "SOP - Storage",
        "Technical File",
        "Validation Report"
    ],
    "biologics": [
        "CMC Summary",
        "Stability Report",
        "Batch Record",
        "SOP - Validation",
        "SOP - Quality Control",
        "Deviation Report",
        "COA"
    ],
    "combination_product": [
        "CTD",
        "Technical File",
        "Risk Assessment",
        "SOP - Manufacturing",
        "SOP - Quality Control",
        "COA"
    ]
}

# SOP update frequency (in months)
SOP_UPDATE_FREQUENCY = 12  # Update SOPs annually

# Renewal warning period (in days)
RENEWAL_WARNING_DAYS = 90  # Alert 90 days before renewal


def get_engine():
    """Create database connection"""
    return create_app_engine()


def normalize_text(value):
    return str(value or "").strip().lower()


def get_required_documents(engine, product_type, country=None, submission_type=None):
    product_type_key = normalize_text(product_type).replace(" ", "_")
    if not product_type_key:
        return []

    country_key = normalize_text(country)
    submission_key = normalize_text(submission_type)

    with engine.connect() as conn:
        query = text("""
        SELECT DISTINCT document_type
        FROM document_requirements
        WHERE lower(product_type) = :product_type
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
          AND required = 1
        """)
        rows = conn.execute(
            query,
            {
                "product_type": product_type_key,
                "country": country_key,
                "submission_type": submission_key,
            },
        ).fetchall()

    documents = [row[0] for row in rows if row[0]]
    if documents:
        return documents

    return REQUIRED_DOCUMENTS.get(product_type_key, REQUIRED_DOCUMENTS.get("pharmaceutical", []))


def check_missing_documents(engine):
    """
    Check for products missing required documents.
    Returns a list of alert dictionaries.
    """
    alerts = []
    
    with engine.connect() as conn:
        # Get all products with their documents
        query = text("""
        SELECT 
            p.product_id,
            p.product_name,
            p.country,
            p.product_type,
            d.document_type,
            COUNT(d.doc_id) as doc_count
        FROM products p
        LEFT JOIN documents d 
        ON p.product_id = d.product_id
        GROUP BY p.product_id, p.product_name, p.country, p.product_type, d.document_type
        ORDER BY p.product_id
        """)
        
        df = pd.read_sql(query, conn)
    
    if df.empty:
        return alerts
    
    # Check each product
    for product_id in df['product_id'].unique():
        product_data = df[df['product_id'] == product_id].iloc[0]
        product_name = product_data['product_name']
        
        # Get uploaded document types
        uploaded_docs = [
            str(doc).strip().lower()
            for doc in df[
                df['product_id'] == product_id
            ]['document_type'].dropna().unique().tolist()
        ]
        
        required = get_required_documents(
            engine,
            product_data.get('product_type'),
            product_data.get('country'),
            None,
        )
        missing = [
            doc for doc in required
            if doc.strip().lower() not in uploaded_docs
        ]
        
        if missing:
            for doc in missing:
                alert = {
                    "alert_type": "Missing Document",
                    "severity": "High",
                    "product_id": product_id,
                    "product_name": product_name,
                    "message": f"Missing: {doc}",
                    "details": f"Product '{product_name}' is missing required document: {doc}",
                    "action": "Upload the missing document",
                    "created_at": datetime.now().isoformat()
                }
                create_alert(
                    engine,
                    product_id=product_id,
                    product_name=product_name,
                    alert_type=alert["alert_type"],
                    severity=alert["severity"],
                    message=alert["message"],
                    details=alert["details"],
                    action=alert["action"],
                )
                alerts.append(alert)
    
    return alerts


def check_outdated_sops(engine):
    """
    Check for SOPs (Standard Operating Procedures) that haven't been updated recently.
    Returns a list of alert dictionaries.
    """
    alerts = []
    
    with engine.connect() as conn:
        # Get all SOP documents
        query = text("""
        SELECT 
            p.product_id,
            p.product_name,
            d.doc_id,
            d.document_name,
            d.document_type,
            d.upload_date,
            d.version
        FROM documents d
        JOIN products p 
        ON d.product_id = p.product_id
        WHERE d.document_type LIKE '%SOP%'
        ORDER BY d.product_id, d.upload_date DESC
        """)
        
        df = pd.read_sql(query, conn)
    
    if df.empty:
        return alerts
    
    # Check each SOP for age
    today = datetime.now().date()
    
    for _, row in df.iterrows():
        upload_date = pd.to_datetime(row['upload_date']).date()
        days_old = (today - upload_date).days
        months_old = days_old / 30
        
        if months_old > SOP_UPDATE_FREQUENCY:
            alert = {
                "alert_type": "Outdated SOP",
                "severity": "Medium" if months_old < SOP_UPDATE_FREQUENCY + 6 else "High",
                "product_id": row['product_id'],
                "product_name": row['product_name'],
                "message": f"Outdated: {row['document_name']} ({int(months_old)} months old)",
                "details": f"SOP '{row['document_name']}' (v{row['version']}) was last updated {int(months_old)} months ago. It should be reviewed and updated.",
                "action": "Review and update the SOP",
                "created_at": datetime.now().isoformat()
            }
            create_alert(
                engine,
                product_id=alert["product_id"],
                product_name=alert["product_name"],
                alert_type=alert["alert_type"],
                severity=alert["severity"],
                message=alert["message"],
                details=alert["details"],
                action=alert["action"],
            )
            alerts.append(alert)
    
    return alerts


def check_overdue_renewals(engine):
    """
    Check for renewals that are overdue or coming due soon.
    Returns a list of alert dictionaries.
    """
    alerts = []
    
    with engine.connect() as conn:
        # Get all submissions with renewal dates
        query = text("""
        SELECT 
            s.submission_id,
            s.product_id,
            s.submission_type,
            s.submission_status,
            s.renewal_due_date,
            p.product_name,
            p.country
        FROM submissions s
        JOIN products p 
        ON s.product_id = p.product_id
        WHERE s.renewal_due_date IS NOT NULL
        AND s.renewal_due_date != ''
        ORDER BY s.renewal_due_date
        """)
        
        df = pd.read_sql(query, conn)
    
    if df.empty:
        return alerts
    
    today = datetime.now().date()
    
    for _, row in df.iterrows():
        try:
            due_date = pd.to_datetime(row['renewal_due_date']).date()
            days_until = (due_date - today).days
            
            if days_until < 0:
                # Overdue
                alert = {
                    "alert_type": "Overdue Renewal",
                    "severity": "Critical",
                    "product_id": row['product_id'],
                    "product_name": row['product_name'],
                    "message": f"OVERDUE: Renewal was due {abs(days_until)} days ago",
                    "details": f"Product '{row['product_name']}' renewal was due on {due_date}. Immediate action required!",
                    "action": "Submit renewal immediately",
                    "created_at": datetime.now().isoformat()
                }
                create_alert(
                    engine,
                    product_id=alert["product_id"],
                    product_name=alert["product_name"],
                    alert_type=alert["alert_type"],
                    severity=alert["severity"],
                    message=alert["message"],
                    details=alert["details"],
                    action=alert["action"],
                )
                alerts.append(alert)
            elif days_until <= RENEWAL_WARNING_DAYS:
                # Coming due soon
                severity = "High" if days_until <= 30 else "Medium"
                alert = {
                    "alert_type": "Renewal Due Soon",
                    "severity": severity,
                    "product_id": row['product_id'],
                    "product_name": row['product_name'],
                    "message": f"Renewal due in {days_until} days",
                    "details": f"Product '{row['product_name']}' renewal is due on {due_date}. Plan submission accordingly.",
                    "action": f"Prepare renewal submission",
                    "created_at": datetime.now().isoformat()
                }
                create_alert(
                    engine,
                    product_id=alert["product_id"],
                    product_name=alert["product_name"],
                    alert_type=alert["alert_type"],
                    severity=alert["severity"],
                    message=alert["message"],
                    details=alert["details"],
                    action=alert["action"],
                )
                alerts.append(alert)
        except:
            # Skip invalid date formats
            continue
    
    return alerts


def get_all_compliance_alerts(engine, sync=True):
    """
    Aggregate stored compliance alerts.
    Returns a DataFrame with persisted alerts sorted by severity.
    """
    if sync:
        check_missing_documents(engine)
        check_outdated_sops(engine)
        check_overdue_renewals(engine)

    with engine.connect() as conn:
        alerts_df = pd.read_sql(
            text("""
            SELECT *
            FROM alerts
            ORDER BY 
                CASE severity
                    WHEN 'Critical' THEN 0
                    WHEN 'High' THEN 1
                    WHEN 'Medium' THEN 2
                    WHEN 'Low' THEN 3
                    ELSE 4
                END,
                created_at DESC
            """),
            conn,
        )

    return alerts_df


def run_scheduled_compliance_checks(engine):
    """
    Run the suite of compliance checks and persist any generated alerts.
    """
    missing = check_missing_documents(engine)
    outdated = check_outdated_sops(engine)
    overdue = check_overdue_renewals(engine)
    return {
        "missing_documents": len(missing),
        "outdated_sops": len(outdated),
        "overdue_renewals": len(overdue),
    }


def get_alert_summary(engine):
    """
    Get summary statistics for compliance alerts.
    Returns a dictionary with counts by type and severity.
    """
    alerts_df = get_all_compliance_alerts(engine)
    
    if alerts_df.empty:
        return {
            "total_alerts": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
            "missing_documents": 0,
            "outdated_sops": 0,
            "overdue_renewals": 0
        }
    
    summary = {
        "total_alerts": len(alerts_df),
        "critical": len(alerts_df[alerts_df['severity'] == 'Critical']),
        "high": len(alerts_df[alerts_df['severity'] == 'High']),
        "medium": len(alerts_df[alerts_df['severity'] == 'Medium']),
        "low": len(alerts_df[alerts_df['severity'] == 'Low']),
        "missing_documents": len(alerts_df[alerts_df['alert_type'] == 'Missing Document']),
        "outdated_sops": len(alerts_df[alerts_df['alert_type'] == 'Outdated SOP']),
        "overdue_renewals": len(alerts_df[alerts_df['alert_type'].str.contains('Renewal')])
    }
    
    return summary


def get_alerts_by_product(engine, product_id, sync=True):
    """
    Get all compliance alerts for a specific product.
    """
    alerts_df = get_all_compliance_alerts(engine, sync=sync)
    
    if alerts_df.empty:
        return pd.DataFrame()
    
    return alerts_df[alerts_df['product_id'] == product_id]


def format_alert_display(alert_row):
    """Format a single alert for display in Streamlit"""
    return {
        "Type": alert_row['alert_type'],
        "Severity": alert_row['severity'],
        "Product": alert_row['product_name'],
        "Message": alert_row['message'],
        "Details": alert_row['details'],
        "Action Required": alert_row['action']
    }
