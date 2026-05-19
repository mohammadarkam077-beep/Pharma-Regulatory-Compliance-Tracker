import streamlit as st
import pandas as pd
import os
import requests
from datetime import datetime
from sqlalchemy import text

from utils.database import get_engine
from utils.expiry_prediction import build_expiry_predictions
from utils.compliance_alerts import (
    get_all_compliance_alerts,
    get_alert_summary,
    format_alert_display,
)
from utils.compliance_workflow import (
    complete_approval,
    ensure_compliance_features,
    get_approval_history,
    get_audit_trail,
    log_audit_event,
    request_approval,
    get_alerts,
    assign_alert,
    update_alert_status,
    get_reference_items,
    save_reference_item,
    delete_reference_item,
    get_pending_approvals,
    escalate_stale_alerts,
)
from utils.pdf_parser import extract_pdf_text
from utils.ai_chatbot import (
    MODEL_OPTIONS,
    ask_bedrock_chatbot,
    get_default_model_id,
    get_default_region,
)
from utils.auth import (
    initialize_auth_session,
    is_authenticated,
    get_current_user,
    get_current_role,
    show_login_page,
    logout,
    require_permission,
    ROLES,
    get_all_users,
    update_user_role,
    deactivate_user,
    register_user
)

# Database connection
engine = get_engine()

PRODUCT_TYPES = [
    "Select product type",
    "Pharmaceutical",
    "Medical Device",
    "Biologics",
    "Combination Product",
    "Other",
]


def get_active_reference_values(engine, table_name, name_column, fallback=None):
    try:
        df = get_reference_items(engine, table_name)
        return df[name_column].tolist() if not df.empty else (fallback or [])
    except Exception:
        return fallback or []

# Page settings
st.set_page_config(
    page_title="Regulatory Compliance Tracker",
    layout="wide"
)


def ensure_document_text_columns(engine):
    """Add PDF extraction columns to older document tables."""
    with engine.connect() as conn:
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
        conn.commit()


def ensure_product_type_column(engine):
    """Add product_type to older product tables."""
    with engine.connect() as conn:
        existing_columns = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(products)" )).fetchall()
        }
        if "product_type" not in existing_columns:
            conn.execute(text("ALTER TABLE products ADD COLUMN product_type TEXT"))
        conn.commit()


def check_compliance_tables(engine):
    """Return which required compliance workflow tables are present."""
    required_tables = [
        "document_requirements",
        "alerts",
        "alert_subscriptions",
        "product_types",
        "submission_types",
        "countries",
        "approval_workflow",
    ]
    with engine.connect() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN (:doc, :alerts, :subs, :ptype, :stype, :countries, :approval)"
                ),
                {
                    "doc": "document_requirements",
                    "alerts": "alerts",
                    "subs": "alert_subscriptions",
                    "ptype": "product_types",
                    "stype": "submission_types",
                    "countries": "countries",
                    "approval": "approval_workflow",
                },
            ).fetchall()
        }
    missing = [table for table in required_tables if table not in existing]
    return existing, missing

# Initialize authentication
initialize_auth_session(engine)
ensure_document_text_columns(engine)
ensure_product_type_column(engine)
ensure_compliance_features(engine)

# Check if user is authenticated
if not is_authenticated():
    show_login_page(engine)
    st.stop()

# User is authenticated - show main app
current_user = get_current_user()
current_role = get_current_role()

# Sidebar header with user info
st.sidebar.markdown(f"### 👤 {current_user['full_name']}")
st.sidebar.caption(f"Role: **{current_role}**")
st.sidebar.divider()

# Sidebar navigation
st.sidebar.title("Navigation")

# Build navigation pages based on role
pages = ["Dashboard"]

if require_permission("view_products"):
    pages.append("Products")
if require_permission("view_submissions"):
    pages.append("Submissions")
if require_permission("view_alerts"):
    pages.append("Smart Compliance Alerts")
if require_permission("view_expiry"):
    pages.append("Expiry Prediction")
if require_permission("view_documents"):
    pages.append("Documents")
if require_permission("ai_assistant"):
    pages.append("AI Assistant")
if current_role in ["Admin", "RA", "QA"]:
    pages.append("Task Inbox")

if current_role in ["Admin", "RA"]:
    pages.append("FDA Data")

if current_role == "Admin":
    pages.append("Configuration")
    pages.append("Policies")
    pages.append("Document Rules")
    pages.append("Alert Management")
if require_permission("manage_users"):
    pages.append("User Management")

page = st.sidebar.radio("Go To", pages)

# Sidebar footer with logout
st.sidebar.divider()
if st.sidebar.button("🚪 Logout", use_container_width=True):
    logout()

# Main title with role badge
st.title("Pharma Regulatory Compliance Tracker")

# Role-based welcome banner
role_colors = {
    "Admin": "🔴",
    "RA": "🟠", 
    "QA": "🟡"
}
role_icon = role_colors.get(current_role, "🟢")
st.markdown(f"{role_icon} **Connected as {current_user['full_name']} ({current_role})**")

# ================= DASHBOARD =================
if page == "Dashboard":

    st.header("Compliance Intelligence Dashboard")

    with engine.connect() as conn:

        # Total products
        total_products = conn.execute(
            text("SELECT COUNT(*) FROM products")
        ).scalar()

        # Approved submissions
        approved_count = conn.execute(
            text("""
            SELECT COUNT(*)
            FROM submissions
            WHERE submission_status = 'Approved'
            """)
        ).scalar()

        # Pending submissions
        pending_count = conn.execute(
            text("""
            SELECT COUNT(*)
            FROM submissions
            WHERE submission_status = 'Pending'
            """)
        ).scalar()

        # Under review submissions
        review_count = conn.execute(
            text("""
            SELECT COUNT(*)
            FROM submissions
            WHERE submission_status = 'Under Review'
            """)
        ).scalar()

        # Load submission data
        dashboard_query = text("""
        SELECT
            s.submission_status,
            s.submission_date,
            s.renewal_due_date,
            p.product_name,
            p.country
        FROM submissions s
        JOIN products p
        ON s.product_id = p.product_id
        """)

        dashboard_df = pd.read_sql(
            dashboard_query,
            conn
        )

    expiry_df = build_expiry_predictions(dashboard_df)
    expiring_soon_count = 0
    if not expiry_df.empty:
        expiring_soon_count = len(
            expiry_df[
                expiry_df["expiry_risk"].isin(["Expired", "Critical", "High"])
            ]
        )

    # KPI ROW
    col1, col2, col3, col4, col5 = st.columns(5)

    col1.metric(
        "Total Products",
        total_products
    )

    col2.metric(
        "Approved",
        approved_count
    )

    col3.metric(
        "Pending",
        pending_count
    )

    col4.metric(
        "Under Review",
        review_count
    )

    col5.metric(
        "Expiry Risk",
        expiring_soon_count
    )

    st.divider()

    # STATUS TABLE
    st.subheader("Submission Status Overview")

    st.dataframe(dashboard_df)

    st.subheader("Expiry Risk Preview")

    if expiry_df.empty:
        st.info("No submissions available for expiry prediction.")
    else:
        st.dataframe(
            expiry_df[
                [
                    "product_name",
                    "country",
                    "submission_status",
                    "predicted_expiry_date",
                    "days_to_expiry",
                    "expiry_risk",
                    "confidence",
                ]
            ].head(10)
        )

    # SMART COMPLIANCE ALERTS
    st.subheader("🚨 Smart Compliance Alerts")
    
    # Get compliance alerts summary
    alert_summary = get_alert_summary(engine)
    
    # Display summary metrics
    alert_col1, alert_col2, alert_col3, alert_col4 = st.columns(4)
    
    with alert_col1:
        st.metric(
            "Critical Alerts",
            alert_summary['critical'],
            delta=None
        )
    
    with alert_col2:
        st.metric(
            "Missing Documents",
            alert_summary['missing_documents']
        )
    
    with alert_col3:
        st.metric(
            "Outdated SOPs",
            alert_summary['outdated_sops']
        )
    
    with alert_col4:
        st.metric(
            "Overdue Renewals",
            alert_summary['overdue_renewals']
        )
    
    # Get detailed alerts
    alerts_df = get_all_compliance_alerts(engine)
    
    if not alerts_df.empty:
        # Filter alerts by severity
        severity_filter = st.selectbox(
            "Filter by Severity:",
            ["All", "Critical", "High", "Medium", "Low"]
        )
        
        if severity_filter != "All":
            filtered_alerts = alerts_df[alerts_df['severity'] == severity_filter]
        else:
            filtered_alerts = alerts_df
        
        # Display alerts with color coding
        for _, alert in filtered_alerts.iterrows():
            if alert['severity'] == 'Critical':
                st.error(f"🔴 **{alert['alert_type']}** - {alert['product_name']}\n{alert['message']}")
            elif alert['severity'] == 'High':
                st.warning(f"🟠 **{alert['alert_type']}** - {alert['product_name']}\n{alert['message']}")
            elif alert['severity'] == 'Medium':
                st.info(f"🟡 **{alert['alert_type']}** - {alert['product_name']}\n{alert['message']}")
            else:
                st.info(f"🟢 **{alert['alert_type']}** - {alert['product_name']}\n{alert['message']}")
        
        # Display detailed alerts table
        st.subheader("Detailed Alert List")
        display_df = filtered_alerts[[
            'alert_type', 'severity', 'product_name', 'message', 'action'
        ]].copy()
        display_df.columns = ['Type', 'Severity', 'Product', 'Message', 'Action Required']
        st.dataframe(display_df, use_container_width=True)
    else:
        st.success("✅ No compliance alerts - All systems are compliant!")
    
    st.divider()
    
    # Original submission alerts
    st.subheader("Submission Status Alerts")

    if pending_count > 0:
        st.warning(
            f"{pending_count} submission(s) are pending."
        )

    if review_count > 0:
        st.info(
            f"{review_count} submission(s) are under review."
        )

    if approved_count > 0:
        st.success(
            f"{approved_count} submission(s) approved."
        )

    if expiring_soon_count > 0:
        st.error(
            f"{expiring_soon_count} registration(s) need expiry attention."
        )

# ================= PRODUCTS =================
elif page == "Products":

    if not require_permission("view_products"):
        st.error("🔒 Access Denied: You don't have permission to view products")
        st.stop()

    st.header("Product Management")

    # Add product form only for users with edit permission
    submit_button = False
    if require_permission("edit_products"):
        st.markdown("### Add New Product")

        product_type_options = ["Select product type"] + get_active_reference_values(
            engine, "product_types", "name", PRODUCT_TYPES[1:]
        )
        country_options = [""] + get_active_reference_values(
            engine, "countries", "country_name", ["India", "USA", "Germany", "Brazil", "Japan"]
        )

        with st.form("product_form"):
            product_name = st.text_input("Product Name")
            dosage_form = st.text_input("Dosage Form")
            strength = st.text_input("Strength")
            product_type = st.selectbox(
                "Product Type",
                product_type_options,
            )
            country = st.selectbox("Country", country_options)
            registration_no = st.text_input("Registration Number")

            submit_button = st.form_submit_button("Add Product")

    # Save product (only if user can edit and submitted form)
    if require_permission("edit_products") and submit_button:
        if product_type == product_type_options[0]:
            st.error("Product type is required. Please select a valid product type.")
        else:
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                    INSERT INTO products
                    (
                        product_name,
                        dosage_form,
                        strength,
                        product_type,
                        country,
                        registration_no
                    )

                    VALUES
                    (
                        :product_name,
                        :dosage_form,
                        :strength,
                        :product_type,
                        :country,
                        :registration_no
                    )
                    """),
                    {
                        "product_name": product_name,
                        "dosage_form": dosage_form,
                        "strength": strength,
                        "product_type": product_type,
                        "country": country,
                        "registration_no": registration_no
                    }
                )
                conn.commit()
                product_id = result.lastrowid

            log_audit_event(
                engine,
                current_user,
                "PRODUCT_CREATED",
                "product",
                product_id,
                f"Product added: {product_name}",
            )
            st.success("Product added successfully!")

    # Display products
    with engine.connect() as conn:
        query = text("SELECT * FROM products")
        df = pd.read_sql(query, conn)

    display_df = df.rename(columns={
        "product_id": "Product ID",
        "product_name": "Product Name",
        "dosage_form": "Dosage Form",
        "strength": "Strength",
        "product_type": "Product Type",
        "country": "Country",
        "registration_no": "Registration Number",
    })

    st.subheader("Products List")
    st.dataframe(display_df)

    if not require_permission("edit_products"):
        st.info("You have view-only access on products. Contact an Admin to add or edit products.")

# ================= SMART COMPLIANCE ALERTS =================
elif page == "Smart Compliance Alerts":
    
    if not require_permission("view_alerts"):
        st.error("🔒 Access Denied: You don't have permission to view alerts")
        st.stop()

    st.header("🚨 Smart Compliance Alerts")
    
    st.markdown("""
    This page displays all compliance alerts across your products:
    - **Missing Documents**: Required documents not yet uploaded
    - **Outdated SOPs**: Standard Operating Procedures older than 12 months
    - **Overdue Renewals**: Renewals that are overdue or due within 90 days
    """)
    
    # Get alert summary
    alert_summary = get_alert_summary(engine)
    
    # Display overview metrics
    st.subheader("Alert Overview")
    col1, col2, col3, col4, col5 = st.columns(5)
    
    with col1:
        st.metric("Total Alerts", alert_summary['total_alerts'])
    
    with col2:
        st.metric("🔴 Critical", alert_summary['critical'])
    
    with col3:
        st.metric("🟠 High", alert_summary['high'])
    
    with col4:
        st.metric("🟡 Medium", alert_summary['medium'])
    
    with col5:
        st.metric("🟢 Low", alert_summary['low'])
    
    st.divider()
    
    # Get detailed alerts
    alerts_df = get_all_compliance_alerts(engine)
    
    if alerts_df.empty:
        st.success("✅ No compliance alerts - All systems are compliant!")
    else:
        # Filter options
        col1, col2 = st.columns(2)
        
        with col1:
            alert_type_filter = st.multiselect(
                "Filter by Alert Type:",
                alerts_df['alert_type'].unique(),
                default=alerts_df['alert_type'].unique().tolist()
            )
        
        with col2:
            severity_filter = st.multiselect(
                "Filter by Severity:",
                ["Critical", "High", "Medium", "Low"],
                default=["Critical", "High", "Medium", "Low"]
            )
        
        # Apply filters
        filtered_alerts = alerts_df[
            (alerts_df['alert_type'].isin(alert_type_filter)) &
            (alerts_df['severity'].isin(severity_filter))
        ]
        
        st.subheader(f"Filtered Alerts ({len(filtered_alerts)})")
        
        if not filtered_alerts.empty:
            # Display alerts with color coding and expandable details
            for idx, (_, alert) in enumerate(filtered_alerts.iterrows()):
                # Color by severity
                if alert['severity'] == 'Critical':
                    color_icon = "🔴"
                    container = st.container(border=True)
                elif alert['severity'] == 'High':
                    color_icon = "🟠"
                    container = st.container(border=True)
                elif alert['severity'] == 'Medium':
                    color_icon = "🟡"
                    container = st.container()
                else:
                    color_icon = "🟢"
                    container = st.container()
                
                with container:
                    col1, col2, col3 = st.columns([1, 3, 1])
                    
                    with col1:
                        st.write(color_icon)
                    
                    with col2:
                        st.markdown(f"**{alert['alert_type']}** - {alert['product_name']}")
                        st.write(f"_Severity: {alert['severity']}_")
                    
                    with col3:
                        st.write(f"_{alert['severity']}_")
                    
                    st.write(alert['message'])
                    
                    with st.expander("📋 Details & Action"):
                        st.write(f"**Details:** {alert['details']}")
                        st.write(f"**Action Required:** {alert['action']}")
                        st.write(f"**Created:** {alert['created_at']}")
            
            # Display summary table
            st.subheader("Alert Summary Table")
            summary_df = filtered_alerts[[
                'alert_type', 'severity', 'product_name', 'message'
            ]].copy()
            summary_df.columns = ['Type', 'Severity', 'Product', 'Message']
            st.dataframe(summary_df, use_container_width=True)
            
            # Export option
            csv = filtered_alerts.to_csv(index=False)
            st.download_button(
                label="📥 Download Alerts as CSV",
                data=csv,
                file_name=f"compliance_alerts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
        else:
            st.info("No alerts match the selected filters.")
    
    st.divider()
    
    # Alert statistics
    st.subheader("Alert Statistics")
    
    if not alerts_df.empty:
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### By Alert Type")
            type_counts = alerts_df['alert_type'].value_counts()
            st.bar_chart(type_counts)
        
        with col2:
            st.markdown("#### By Severity")
            severity_counts = alerts_df['severity'].value_counts()
            severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
            severity_counts = severity_counts.reindex([k for k, v in sorted(severity_order.items(), key=lambda x: x[1])])
            st.bar_chart(severity_counts)

# ================= CONFIGURATION =================
elif page == "Configuration":
    if current_role != "Admin":
        st.error("🔒 Access Denied: Configuration is only available to Admin users.")
        st.stop()

    st.header("Compliance Reference Data")
    st.markdown(
        "Use this page to manage product types, submission types, and supported countries used by the compliance engine."
    )

    with engine.connect() as conn:
        product_types_df = get_reference_items(engine, "product_types")
        submission_types_df = get_reference_items(engine, "submission_types")
        countries_df = get_reference_items(engine, "countries")

    with st.expander("Add or update reference data"):
        with st.form("reference_data_form"):
            section = st.selectbox(
                "Configure",
                ["Product Types", "Submission Types", "Countries"],
            )
            name = st.text_input("Name")
            description = st.text_area("Description")
            active = st.checkbox("Active", value=True)
            save_reference = st.form_submit_button("Save Reference Item")

        if save_reference:
            table_map = {
                "Product Types": "product_types",
                "Submission Types": "submission_types",
                "Countries": "countries",
            }
            if not name.strip():
                st.error("Name is required to save a reference item.")
            else:
                save_reference_item(
                    engine,
                    table_map[section],
                    name.strip(),
                    description.strip(),
                    1 if active else 0,
                )
                st.success(f"Saved {section[:-1]} '{name.strip()}'.")
                st.rerun()

    st.divider()
    st.subheader("Current Reference Configuration")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Product Types**")
        st.dataframe(product_types_df[["product_type_id", "name", "description", "is_active"]], use_container_width=True)
        delete_product = st.selectbox("Delete product type", [""] + product_types_df["name"].tolist())
        if delete_product and st.button("Delete selected product type"):
            row = product_types_df[product_types_df["name"] == delete_product].iloc[0]
            delete_reference_item(engine, "product_types", int(row["product_type_id"]))
            st.success(f"Deleted product type {delete_product}")
            st.rerun()

    with col2:
        st.markdown("**Submission Types**")
        st.dataframe(submission_types_df[["submission_type_id", "name", "description", "is_active"]], use_container_width=True)
        delete_submission = st.selectbox("Delete submission type", [""] + submission_types_df["name"].tolist())
        if delete_submission and st.button("Delete selected submission type"):
            row = submission_types_df[submission_types_df["name"] == delete_submission].iloc[0]
            delete_reference_item(engine, "submission_types", int(row["submission_type_id"]))
            st.success(f"Deleted submission type {delete_submission}")
            st.rerun()

    with col3:
        st.markdown("**Countries**")
        st.dataframe(countries_df[["country_id", "country_name", "region", "is_active"]], use_container_width=True)
        delete_country = st.selectbox("Delete country", [""] + countries_df["country_name"].tolist())
        if delete_country and st.button("Delete selected country"):
            row = countries_df[countries_df["country_name"] == delete_country].iloc[0]
            delete_reference_item(engine, "countries", int(row["country_id"]))
            st.success(f"Deleted country {delete_country}")
            st.rerun()

# ================= POLICIES =================
elif page == "Policies":
    if current_role != "Admin":
        st.error("🔒 Access Denied: Policies are only available to Admin users.")
        st.stop()

    st.header("SOP / Policy Management")
    st.markdown("Create SOP policies and steps; assign to submissions to generate task checklists.")

    from utils.sop_engine import create_policy, add_policy_step, get_policies, get_policy_steps

    with st.expander("Create new policy"):
        with st.form("policy_form"):
            policy_name = st.text_input("Policy name")
            policy_description = st.text_area("Description")
            policy_product_type = st.selectbox(
                "Product Type",
                ["All"] + get_active_reference_values(engine, "product_types", "name", PRODUCT_TYPES[1:]),
            )
            policy_country = st.selectbox(
                "Country",
                ["All"] + get_active_reference_values(
                    engine,
                    "countries",
                    "country_name",
                    ["India", "USA", "Germany", "Brazil", "Japan"],
                ),
            )
            policy_submission_type = st.selectbox(
                "Submission Type",
                ["All"] + get_active_reference_values(
                    engine,
                    "submission_types",
                    "name",
                    [
                        "New Registration",
                        "Renewal",
                        "Variation",
                        "Re-Registration",
                        "Amendment",
                        "Clinical Trial Application",
                        "Import License",
                        "Registration Transfer",
                    ],
                ),
            )
            save_policy = st.form_submit_button("Create Policy")
        if save_policy:
            if not policy_name.strip():
                st.error("Policy name is required")
            else:
                create_policy(
                    engine,
                    policy_name.strip(),
                    policy_description.strip(),
                    None if policy_product_type == "All" else policy_product_type,
                    None if policy_country == "All" else policy_country,
                    None if policy_submission_type == "All" else policy_submission_type,
                )
                st.success(f"Policy '{policy_name.strip()}' created")
                st.rerun()

    policies_df = get_policies(engine)
    st.subheader("Policies")
    if policies_df.empty:
        st.info("No policies configured yet.")
    else:
        for _, p in policies_df.iterrows():
            st.markdown(f"**{p['name']}** — {p.get('description','')}")
            policy_criteria = []
            if p.get('product_type'):
                policy_criteria.append(f"Product Type: {p['product_type']}")
            if p.get('country'):
                policy_criteria.append(f"Country: {p['country']}")
            if p.get('submission_type'):
                policy_criteria.append(f"Submission Type: {p['submission_type']}")
            if policy_criteria:
                st.caption(" | ".join(policy_criteria))
            steps = get_policy_steps(engine, int(p['policy_id']))
            if not steps.empty:
                st.table(steps[["step_order","title","role","due_days","instructions"]])

    with st.expander("Add step to policy"):
        with st.form("policy_step_form"):
            policy_choice = st.selectbox("Policy", policies_df['name'].tolist() if not policies_df.empty else [])
            step_order = st.number_input("Step order", min_value=1, value=1)
            step_title = st.text_input("Step title")
            step_role = st.text_input("Role responsible (e.g., RA, QA)")
            step_due_days = st.number_input("Due in (days)", min_value=0, value=7)
            step_instructions = st.text_area("Instructions")
            add_step_btn = st.form_submit_button("Add Step")

        if add_step_btn:
            if not policy_choice:
                st.error("Select a policy")
            elif not step_title.strip():
                st.error("Step title required")
            else:
                policy_row = policies_df[policies_df['name'] == policy_choice].iloc[0]
                add_policy_step(engine, int(policy_row['policy_id']), int(step_order), step_title.strip(), step_role.strip(), int(step_due_days), step_instructions.strip())
                st.success("Step added")
                st.rerun()

    # Admin helper: assign policies to existing submissions (one-time)
    with st.expander("Admin: Assign policies to existing submissions (one-time)"):
        if current_role == "Admin":
            from utils.sop_engine import get_matching_policies, assign_policy_to_submission, get_policies

            if st.button("Assign policies to all submissions"):
                assigned_total = 0
                with engine.connect() as conn:
                    subs = conn.execute(text("SELECT submission_id, product_id, submission_type FROM submissions")).fetchall()
                    for s in subs:
                        submission_id = int(s[0])
                        product_id = int(s[1]) if s[1] is not None else None
                        submission_type = s[2]
                        # find product attrs
                        product_type = None
                        country = None
                        if product_id is not None:
                            prow = conn.execute(text("SELECT product_type, country FROM products WHERE product_id = :product_id"), {"product_id": product_id}).fetchone()
                            if prow:
                                product_type, country = prow

                        policies_df = get_matching_policies(engine, product_type, country, submission_type)
                        if policies_df.empty:
                            policies_df = get_policies(engine)
                        for _, p in policies_df.iterrows():
                            created = assign_policy_to_submission(engine, int(p['policy_id']), submission_id, product_id)
                            assigned_total += int(created or 0)
                st.success(f"Assigned {assigned_total} policy steps to existing submissions.")

# ================= TASK INBOX =================
elif page == "Task Inbox":
    st.header("Task Inbox")
    st.markdown("Review and manage SOP task assignments generated from matched policies.")

    from utils.sop_engine import get_user_assignments, claim_assignment, complete_assignment

    my_assignments = get_user_assignments(engine, user_id=current_user["user_id"])
    unassigned_tasks = get_user_assignments(engine, status="Open", unassigned=True)

    with st.expander("My Tasks"):
        if my_assignments.empty:
            st.info("No tasks assigned to you yet.")
        else:
            for _, row in my_assignments.iterrows():
                assignment_id = int(row["assignment_id"])
                with st.container():
                    st.markdown(f"**{row['policy_name']}** — {row['step_title']} ({row['status']})")
                    st.write(f"Submission: {row.get('submission_type','N/A')} | Product: {row.get('product_name','N/A')}")
                    if row.get('due_date'):
                        st.caption(f"Due: {row['due_date']}")
                    if row["status"] != "Completed":
                        if st.button("Mark Completed", key=f"complete_{assignment_id}"):
                            complete_assignment(engine, assignment_id, current_user["user_id"])
                            st.success("Task marked completed")
                            st.rerun()

    with st.expander("Available Tasks"):
        if unassigned_tasks.empty:
            st.info("No unassigned tasks available.")
        else:
            for _, row in unassigned_tasks.iterrows():
                assignment_id = int(row["assignment_id"])
                with st.container():
                    st.markdown(f"**{row['policy_name']}** — {row['step_title']}")
                    st.write(f"Submission: {row.get('submission_type','N/A')} | Product: {row.get('product_name','N/A')}")
                    if row.get('due_date'):
                        st.caption(f"Due: {row['due_date']}")
                    if st.button("Claim Task", key=f"claim_{assignment_id}"):
                        claim_assignment(engine, assignment_id, current_user["user_id"])
                        st.success("Task claimed")
                        st.rerun()

# ================= FDA LIVE DATA =================
elif page == "FDA Data":
    st.header("FDA Live Data")
    st.markdown("Fetch live product records from the FDA openFDA API and import them into the product registry.")

    from utils.fda_loader import fetch_fda_drug_labels, import_fda_products, load_sample_fda_products

    search_query = st.text_input("Search FDA product name or ingredient", "aspirin")
    limit = st.number_input("Number of records to fetch", min_value=1, max_value=50, value=20)
    proxy_mode = st.radio(
        "Connection mode",
        ["Auto (use environment proxy settings)", "Direct (ignore proxy settings)"],
        index=0,
        help="If your environment proxy is unavailable, choose Direct to bypass proxy settings.",
    )
    col1, col2 = st.columns([2, 1])
    with col1:
        fetch_button = st.button("Fetch FDA Records")
    with col2:
        sample_button = st.button("Load sample FDA demo data")

    if "fda_records" not in st.session_state:
        st.session_state["fda_records"] = []

    if fetch_button:
        try:
            mode = "auto" if proxy_mode.startswith("Auto") else "direct"
            st.session_state["fda_records"] = fetch_fda_drug_labels(limit=limit, search_query=search_query, proxy_mode=mode)
            st.success(f"Loaded {len(st.session_state['fda_records'])} FDA records.")
        except requests.exceptions.ProxyError as exc:
            st.error(
                "Proxy error while fetching FDA data. Check your HTTP(S)_PROXY/NO_PROXY environment settings or select Direct mode."
            )
            st.error(str(exc))
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            st.error(f"FDA API returned HTTP {status}. The endpoint may be unavailable or blocked.")
            st.error(str(exc))
            st.info("Use the sample demo data button below if live FDA access is unavailable.")
        except Exception as exc:
            st.error(f"Failed to fetch FDA data: {exc}")
            st.info("Use the sample demo data button below if live FDA access is unavailable.")

    if sample_button:
        st.session_state["fda_records"] = load_sample_fda_products()
        st.success("Loaded sample FDA demo data.")

    records = st.session_state.get("fda_records", [])
    if records:
        df = pd.DataFrame(records)
        st.dataframe(df[["product_name", "dosage_form", "strength", "country", "registration_no", "product_type"]], use_container_width=True)

        selected_ids = st.multiselect(
            "Select rows to import",
            options=list(range(len(records))),
            format_func=lambda idx: f"{records[idx]['product_name']} ({records[idx]['registration_no'] or 'no-reg'})",
        )

        create_submissions = st.checkbox("Create New Registration submissions for imported products", value=True)
        create_workflow = st.checkbox("Generate policy workflow tasks for created submissions", value=True)

        if st.button("Import selected FDA products"):
            chosen = [records[i] for i in selected_ids] if selected_ids else records
            result = import_fda_products(
                engine,
                chosen,
                create_submissions=create_submissions,
                create_workflow=create_workflow,
            )
            st.success(
                f"Imported {result['inserted']} new products, updated {result['updated']} existing products, "
                f"created {result['created_submissions']} submissions, and generated {result['created_workflows']} workflow assignments."
            )
            st.rerun()
    else:
        st.info("No FDA records loaded yet. Use the fetch button to query FDA live data.")

# ================= DOCUMENT RULES =================
elif page == "Document Rules":
    if current_role != "Admin":
        st.error("🔒 Access Denied: Document Rules are only available to Admin users.")
        st.stop()

    st.header("Document Requirement Rules")
    st.markdown(
        "Use this page to configure required document rules by product type, country, and submission type."
    )

    existing_tables, missing_tables = check_compliance_tables(engine)
    if missing_tables:
        st.error(
            f"Compliance schema check failed: missing tables {', '.join(missing_tables)}."
        )
    else:
        st.success(
            "Compliance workflow schema is active. Required tables are available."
        )

    with st.expander("Add or update document requirement"):
        with st.form("rule_form"):
            rule_product_type = st.selectbox(
                "Product Type",
                get_active_reference_values(
                    engine,
                    "product_types",
                    "name",
                    ["Pharmaceutical", "Medical Device", "Biologics", "Combination Product", "Other"],
                ),
            )
            rule_country = st.selectbox(
                "Country",
                ["All"] + get_active_reference_values(
                    engine,
                    "countries",
                    "country_name",
                    ["India", "USA", "Germany", "Brazil", "Japan"],
                ),
            )
            rule_submission_type = st.selectbox(
                "Submission Type",
                ["All"] + get_active_reference_values(
                    engine,
                    "submission_types",
                    "name",
                    [
                        "New Registration",
                        "Renewal",
                        "Variation",
                        "Re-Registration",
                        "Amendment",
                        "Clinical Trial Application",
                        "Import License",
                        "Registration Transfer",
                    ],
                ),
            )
            rule_document_type = st.text_input("Document Type")
            rule_required = st.checkbox("Required", value=True)
            rule_submit = st.form_submit_button("Save Rule")

        if rule_submit:
            if not rule_document_type.strip():
                st.error("Document Type is required.")
            else:
                with engine.connect() as conn:
                    conn.execute(
                        text("""
                        INSERT INTO document_requirements (
                            product_type, country, submission_type,
                            document_type, required, created_at, updated_at
                        ) VALUES (
                            :product_type, :country, :submission_type,
                            :document_type, :required, :created_at, :updated_at
                        )
                        """),
                        {
                            "product_type": rule_product_type,
                            "country": "" if rule_country == "All" else rule_country.strip(),
                            "submission_type": "" if rule_submission_type == "All" else rule_submission_type.strip(),
                            "document_type": rule_document_type.strip(),
                            "required": 1 if rule_required else 0,
                            "created_at": datetime.now().isoformat(),
                            "updated_at": datetime.now().isoformat(),
                        },
                    )
                    conn.commit()
                st.success("Document requirement rule saved.")

    st.divider()
    with engine.connect() as conn:
        rules_df = pd.read_sql(
            text("SELECT * FROM document_requirements ORDER BY product_type, country, submission_type, document_type"),
            conn,
        )

    if rules_df.empty:
        st.info("No document rules have been configured yet.")
    else:
        st.subheader("Configured Document Requirement Rules")
        display_rules = rules_df.rename(columns={
            "requirement_id": "Rule ID",
            "product_type": "Product Type",
            "country": "Country",
            "submission_type": "Submission Type",
            "document_type": "Document Type",
            "required": "Required",
            "created_at": "Created At",
            "updated_at": "Updated At",
        })
        st.dataframe(display_rules, use_container_width=True)

        delete_ids = st.multiselect(
            "Delete selected rule IDs",
            rules_df["requirement_id"].tolist(),
        )
        if st.button("Delete selected rules") and delete_ids:
            ids_sql = ",".join(str(int(item)) for item in delete_ids)
            with engine.connect() as conn:
                conn.execute(
                    text(f"DELETE FROM document_requirements WHERE requirement_id IN ({ids_sql})")
                )
                conn.commit()
            st.success("Selected rules deleted.")

# ================= ALERT MANAGEMENT =================
elif page == "Alert Management":
    if current_role != "Admin":
        st.error("🔒 Access Denied: Alert Management is only available to Admin users.")
        st.stop()

    st.header("Alert Management")
    st.markdown(
        "Review, assign, and update persisted alerts from the compliance engine."
    )

    existing_tables, missing_tables = check_compliance_tables(engine)
    if missing_tables:
        st.error(
            f"Compliance schema check failed: missing tables {', '.join(missing_tables)}."
        )
    else:
        st.success(
            "Compliance workflow schema is active. Required tables are available."
        )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Run scheduled compliance checks"):
            from utils.compliance_alerts import run_scheduled_compliance_checks
            results = run_scheduled_compliance_checks(engine)
            st.success(
                f"Scheduled checks complete: {results['missing_documents']} missing document alerts, "
                f"{results['outdated_sops']} outdated SOP alerts, {results['overdue_renewals']} overdue renewal alerts."
            )
    with col2:
        if st.button("Escalate stale alerts"):
            escalated_count = escalate_stale_alerts(engine, days_threshold=7)
            st.success(f"Escalated {escalated_count} stale alert(s) older than 7 days.")

    alerts_df = get_alerts(engine)
    status_filter = st.multiselect(
        "Status",
        ["Open", "In Progress", "Resolved"],
        default=["Open", "In Progress", "Resolved"],
    )
    filtered_alerts = alerts_df[alerts_df["status"].isin(status_filter)] if not alerts_df.empty else alerts_df

    if filtered_alerts.empty:
        st.info("No alerts available.")
    else:
        st.subheader("Alerts")
        st.dataframe(filtered_alerts, use_container_width=True)

        alert_ids = filtered_alerts["alert_id"].tolist()
        selected_alert = st.selectbox(
            "Select alert to update",
            alert_ids,
            format_func=lambda alert_id: (
                f"#{alert_id} - {filtered_alerts[filtered_alerts['alert_id'] == alert_id]['alert_type'].values[0]}"
            ) if alert_id else "",
        )

        selected_status = st.selectbox(
            "Change status",
            ["Open", "In Progress", "Resolved"],
        )
        user_df = get_all_users(engine)
        user_options = {row['username']: row['user_id'] for _, row in user_df.iterrows()}
        selected_assignee = st.selectbox(
            "Assign to user",
            ["Unassigned"] + list(user_options.keys()),
        )
        assign_button = st.button("Update alert")

        if assign_button and selected_alert:
            if selected_status:
                update_alert_status(engine, selected_alert, selected_status)
            if selected_assignee != "Unassigned":
                assign_alert(engine, selected_alert, user_options[selected_assignee])
            st.success("Alert updated successfully.")

    if not alerts_df.empty:
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Open Alerts", len(alerts_df[alerts_df['status'] == 'Open']))
            st.metric("In Progress", len(alerts_df[alerts_df['status'] == 'In Progress']))
        with col2:
            st.metric("Resolved", len(alerts_df[alerts_df['status'] == 'Resolved']))
            st.metric("Total Alerts", len(alerts_df))

# ================= SUBMISSIONS =================
elif page == "Submissions":
    
    if not require_permission("view_submissions"):
        st.error("🔒 Access Denied: You don't have permission to view submissions")
        st.stop()

    st.header("Regulatory Submission Tracking")

    # Load products
    with engine.connect() as conn:

        product_query = text("""
        SELECT product_id, product_name
        FROM products
        """)

        product_df = pd.read_sql(product_query, conn)

    # If no products
    if product_df.empty:

        st.warning("Please add products first.")

    else:

        # Product dropdown mapping
        product_options = {
            row["product_name"]: row["product_id"]
            for _, row in product_df.iterrows()
        }

        # Submission form
        submit_submission = False
        if require_permission("edit_submissions"):
            with st.form("submission_form"):
                selected_product = st.selectbox(
                    "Select Product",
                    list(product_options.keys())
                )

                submission_type = st.selectbox(
                    "Submission Type",
                    get_active_reference_values(
                        engine,
                        "submission_types",
                        "name",
                        [
                            "New Registration",
                            "Renewal",
                            "Variation",
                            "Re-Registration",
                            "Amendment",
                            "Clinical Trial Application",
                            "Import License",
                            "Registration Transfer"
                        ],
                    )
                )

                submission_status = st.selectbox(
                    "Submission Status",
                    [
                        "Pending",
                        "Under Review",
                        "Approved",
                        "Rejected"
                    ]
                )

                submission_date = st.date_input(
                    "Submission Date"
                )

                renewal_due_date = st.date_input(
                    "Renewal Due Date"
                )

                submit_submission = st.form_submit_button(
                    "Add Submission"
                )

        # Save submission
        if require_permission("edit_submissions") and submit_submission:

            product_id = product_options[selected_product]

            with engine.connect() as conn:

                result = conn.execute(
                    text("""
                    INSERT INTO submissions
                    (
                        product_id,
                        submission_type,
                        submission_status,
                        submission_date,
                        renewal_due_date
                    )

                    VALUES
                    (
                        :product_id,
                        :submission_type,
                        :submission_status,
                        :submission_date,
                        :renewal_due_date
                    )
                    """),

                    {
                        "product_id": product_id,
                        "submission_type": submission_type,
                        "submission_status": submission_status,
                        "submission_date": str(submission_date),
                        "renewal_due_date": str(renewal_due_date)
                    }
                )

                conn.commit()
                submission_id = result.lastrowid

            # Generate SOP policy assignments/tasks for this submission using matched policies
            try:
                from utils.sop_engine import assign_policy_to_submission, get_matching_policies
                product_type = None
                country = None
                with engine.connect() as conn:
                    product_row = conn.execute(
                        text("SELECT product_type, country FROM products WHERE product_id = :product_id"),
                        {"product_id": product_id},
                    ).fetchone()
                    if product_row:
                        product_type, country = product_row

                policies_df = get_matching_policies(engine, product_type, country, submission_type)
                if policies_df.empty:
                    from utils.sop_engine import get_policies
                    policies_df = get_policies(engine)
                for _, p in policies_df.iterrows():
                    assign_policy_to_submission(engine, int(p['policy_id']), submission_id, product_id)
            except Exception:
                pass
            log_audit_event(
                engine,
                current_user,
                "SUBMISSION_CREATED",
                "submission",
                submission_id,
                f"{submission_type} for product_id {product_id} set to {submission_status}",
            )
            st.success("Submission added successfully!")
        elif not require_permission("edit_submissions"):
            st.info("You can view submissions but do not have permission to create or edit them.")

        # Display submissions
        with engine.connect() as conn:

            submission_display_query = text("""
            SELECT
                s.submission_id,
                p.product_name,
                s.submission_type,
                s.submission_status,
                s.submission_date,
                s.renewal_due_date,
                s.approval_status,
                s.approval_requested_by,
                s.approved_by,
                s.approved_at

            FROM submissions s

            JOIN products p
            ON s.product_id = p.product_id
            """)

            submissions_df = pd.read_sql(
                submission_display_query,
                conn
            )

        st.subheader("Submission Records")

        st.dataframe(submissions_df)

        if require_permission("approve_submissions"):
            pending_approvals_df = get_pending_approvals(engine)
            st.subheader("Pending Approval Requests")
            if pending_approvals_df.empty:
                st.info("No pending approval requests.")
            else:
                st.dataframe(pending_approvals_df, use_container_width=True)

        if require_permission("edit_submissions") and not submissions_df.empty:
            st.subheader("Submission Approval Workflow")
            workflow_submission = st.selectbox(
                "Select submission",
                submissions_df["submission_id"].tolist(),
                format_func=lambda submission_id: (
                    f"#{submission_id} - "
                    f"{submissions_df[submissions_df['submission_id'] == submission_id]['product_name'].values[0]}"
                ),
                key="submission_workflow_select",
            )
            selected_submission = submissions_df[
                submissions_df["submission_id"] == workflow_submission
            ].iloc[0]
            st.caption(f"Current approval status: {selected_submission['approval_status'] or 'Draft'}")

            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("Request Review", key="request_submission_review"):
                    request_approval(engine, current_user, "submission", int(workflow_submission))
                    st.success("Submission sent for review.")
                    st.rerun()

            if require_permission("approve_submissions"):
                approval_notes = st.text_input(
                    "Review notes",
                    key="submission_approval_notes",
                )
                with col2:
                    if st.button("Approve", key="approve_submission"):
                        complete_approval(
                            engine,
                            current_user,
                            "submission",
                            int(workflow_submission),
                            "Approved",
                            approval_notes,
                        )
                        st.success("Submission approved.")
                        st.rerun()
                with col3:
                    if st.button("Reject", key="reject_submission"):
                        complete_approval(
                            engine,
                            current_user,
                            "submission",
                            int(workflow_submission),
                            "Rejected",
                            approval_notes,
                        )
                        st.warning("Submission rejected.")
                        st.rerun()

# ================= EXPIRY PREDICTION =================
elif page == "Expiry Prediction":
    
    if not require_permission("view_expiry"):
        st.error("🔒 Access Denied: You don't have permission to view expiry predictions")
        st.stop()

    st.header("Expiry Prediction Engine")

    with engine.connect() as conn:

        expiry_query = text("""
        SELECT
            s.submission_id,
            p.product_name,
            p.dosage_form,
            p.strength,
            p.country,
            p.registration_no,
            s.submission_type,
            s.submission_status,
            s.submission_date,
            s.renewal_due_date

        FROM submissions s

        JOIN products p
        ON s.product_id = p.product_id
        """)

        expiry_source_df = pd.read_sql(
            expiry_query,
            conn
        )

    if expiry_source_df.empty:

        st.warning("Add products and submissions before running expiry predictions.")

    else:

        expiry_predictions_df = build_expiry_predictions(expiry_source_df)

        total_records = len(expiry_predictions_df)
        expired_count = len(
            expiry_predictions_df[
                expiry_predictions_df["expiry_risk"] == "Expired"
            ]
        )
        urgent_count = len(
            expiry_predictions_df[
                expiry_predictions_df["expiry_risk"].isin(["Critical", "High"])
            ]
        )
        medium_count = len(
            expiry_predictions_df[
                expiry_predictions_df["expiry_risk"] == "Medium"
            ]
        )

        col1, col2, col3, col4 = st.columns(4)

        col1.metric("Tracked Records", total_records)
        col2.metric("Expired", expired_count)
        col3.metric("Due Within 90 Days", urgent_count)
        col4.metric("Due Within 180 Days", medium_count)

        st.divider()

        risk_filter = st.multiselect(
            "Filter by Expiry Risk",
            ["Expired", "Critical", "High", "Medium", "Low", "Unknown"],
            default=["Expired", "Critical", "High", "Medium"],
        )

        country_filter = st.multiselect(
            "Filter by Country",
            sorted(expiry_predictions_df["country"].dropna().unique()),
        )

        filtered_predictions_df = expiry_predictions_df.copy()

        if risk_filter:
            filtered_predictions_df = filtered_predictions_df[
                filtered_predictions_df["expiry_risk"].isin(risk_filter)
            ]

        if country_filter:
            filtered_predictions_df = filtered_predictions_df[
                filtered_predictions_df["country"].isin(country_filter)
            ]

        st.subheader("Predicted Expiry Register")

        st.dataframe(
            filtered_predictions_df[
                [
                    "submission_id",
                    "product_name",
                    "country",
                    "registration_no",
                    "submission_type",
                    "submission_status",
                    "submission_date",
                    "renewal_due_date",
                    "predicted_expiry_date",
                    "days_to_expiry",
                    "expiry_risk",
                    "confidence",
                    "prediction_basis",
                    "recommended_action",
                ]
            ],
            use_container_width=True,
        )

        csv_data = filtered_predictions_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            "Download Prediction Report",
            data=csv_data,
            file_name="expiry_predictions.csv",
            mime="text/csv",
        )

# ================= DOCUMENTS =================
elif page == "Documents":
    
    if not require_permission("view_documents"):
        st.error("🔒 Access Denied: You don't have permission to view documents")
        st.stop()

    st.header("Regulatory Document Management")

    # Load products
    with engine.connect() as conn:

        product_query = text("""
        SELECT product_id, product_name
        FROM products
        """)

        product_df = pd.read_sql(product_query, conn)

    if product_df.empty:

        st.warning("Please add products first.")

    else:

        product_options = {
            row["product_name"]: row["product_id"]
            for _, row in product_df.iterrows()
        }

        # Upload form
        submit_document = False
        uploaded_file = None
        if require_permission("upload_documents"):
            with st.form("document_form"):
                selected_product = st.selectbox(
                    "Select Product",
                    list(product_options.keys())
                )

                document_type = st.selectbox(
                    "Document Type",
                    [
                        "SOP - Manufacturing",
                        "SOP - Quality Control",
                        "SOP - Validation",
                        "CTA Form",
                        "CTD",
                        "Safety Report",
                        "Stability Report",
                        "Validation Report",
                        "COA",
                        "Batch Record",
                        "Device Master Record",
                        "Device History Record",
                        "Risk Assessment",
                        "Technical File",
                        "Deviation Report",
                        "Artwork",
                        "Other"
                    ]
                )

                version = st.text_input(
                    "Document Version"
                )

                uploaded_file = st.file_uploader(
                    "Upload Document",
                    type=["pdf", "doc", "docx", "txt", "xlsx", "xls", "png", "jpg", "jpeg"]
                )

                submit_document = st.form_submit_button(
                    "Upload Document"
                )

        # Save uploaded file
        if require_permission("upload_documents") and submit_document and uploaded_file is not None:

            product_id = product_options[selected_product]
            file_bytes = uploaded_file.getvalue()
            extraction_status = "Not parsed"
            extraction_pages = 0
            extracted_text = ""

            is_sop_pdf = (
                document_type == "SOP"
                and uploaded_file.name.lower().endswith(".pdf")
            )
            if is_sop_pdf:
                extraction_result = extract_pdf_text(file_bytes)
                extracted_text = extraction_result["text"]
                extraction_pages = extraction_result["page_count"]
                extraction_status = extraction_result["message"]

            # File path
            file_path = os.path.join(
                "uploads",
                uploaded_file.name
            )

            # Save file
            with open(file_path, "wb") as f:
                f.write(file_bytes)

            # Save metadata
            with engine.connect() as conn:

                result = conn.execute(
                    text("""
                    INSERT INTO documents
                    (
                        product_id,
                        document_name,
                        document_type,
                        version,
                        upload_date,
                        file_path,
                        extracted_text,
                        extraction_status,
                        extraction_pages
                    )

                    VALUES
                    (
                        :product_id,
                        :document_name,
                        :document_type,
                        :version,
                        :upload_date,
                        :file_path,
                        :extracted_text,
                        :extraction_status,
                        :extraction_pages
                    )
                    """),

                    {
                        "product_id": product_id,
                        "document_name": uploaded_file.name,
                        "document_type": document_type,
                        "version": version,
                        "upload_date": str(datetime.now()),
                        "file_path": file_path,
                        "extracted_text": extracted_text,
                        "extraction_status": extraction_status,
                        "extraction_pages": extraction_pages
                    }
                )

                conn.commit()
                doc_id = result.lastrowid

            log_audit_event(
                engine,
                current_user,
                "DOCUMENT_UPLOADED",
                "document",
                doc_id,
                f"{document_type} uploaded: {uploaded_file.name}",
            )
            st.success("Document uploaded successfully!")
            if is_sop_pdf:
                if extracted_text:
                    st.success(extraction_status)
                else:
                    st.warning(extraction_status)

        if not require_permission("upload_documents"):
            st.info("You can view documents but do not have upload permissions.")

        # Display documents
        with engine.connect() as conn:

            documents_query = text("""
            SELECT
                d.doc_id,
                p.product_name,
                d.document_name,
                d.document_type,
                d.version,
                d.upload_date,
                d.extraction_status,
                d.extraction_pages,
                d.approval_status,
                d.approval_requested_by,
                d.approved_by,
                d.approved_at,
                d.extracted_text

            FROM documents d

            JOIN products p
            ON d.product_id = p.product_id
            """)

            documents_df = pd.read_sql(
                documents_query,
                conn
            )

        st.subheader("Uploaded Documents")

        display_documents_df = documents_df.drop(columns=["extracted_text"])
        st.dataframe(display_documents_df)

        sop_text_df = documents_df[
            documents_df["extracted_text"].fillna("").str.len() > 0
        ]
        if not sop_text_df.empty:
            st.subheader("Extracted SOP Text")
            selected_doc = st.selectbox(
                "Select SOP PDF",
                sop_text_df["document_name"].tolist()
            )
            selected_row = sop_text_df[
                sop_text_df["document_name"] == selected_doc
            ].iloc[0]
            st.text_area(
                "Parsed Text",
                selected_row["extracted_text"],
                height=320
            )

        if require_permission("upload_documents") and not documents_df.empty:
            st.subheader("Document Approval Workflow")
            workflow_doc = st.selectbox(
                "Select document",
                documents_df["doc_id"].tolist(),
                format_func=lambda doc_id: (
                    f"#{doc_id} - "
                    f"{documents_df[documents_df['doc_id'] == doc_id]['document_name'].values[0]}"
                ),
                key="document_workflow_select",
            )
            selected_document = documents_df[
                documents_df["doc_id"] == workflow_doc
            ].iloc[0]
            st.caption(f"Current approval status: {selected_document['approval_status'] or 'Draft'}")

            col1, col2, col3 = st.columns(3)
            with col1:
                if st.button("Request Review", key="request_document_review"):
                    request_approval(engine, current_user, "document", int(workflow_doc))
                    st.success("Document sent for review.")
                    st.rerun()

            if require_permission("approve_documents"):
                approval_notes = st.text_input(
                    "Review notes",
                    key="document_approval_notes",
                )
                with col2:
                    if st.button("Approve", key="approve_document"):
                        complete_approval(
                            engine,
                            current_user,
                            "document",
                            int(workflow_doc),
                            "Approved",
                            approval_notes,
                        )
                        st.success("Document approved.")
                        st.rerun()
                with col3:
                    if st.button("Reject", key="reject_document"):
                        complete_approval(
                            engine,
                            current_user,
                            "document",
                            int(workflow_doc),
                            "Rejected",
                            approval_notes,
                        )
                        st.warning("Document rejected.")
                        st.rerun()

# ================= AI ASSISTANT =================
elif page == "AI Assistant":
    
    if not require_permission("ai_assistant"):
        st.error("🔒 Access Denied: You don't have permission to use the AI Assistant")
        st.stop()

    st.header("AI Regulatory Chatbot")

    # Load documents
    with engine.connect() as conn:

        ai_query = text("""
        SELECT
            d.doc_id,
            p.product_name,
            d.document_name,
            d.document_type,
            d.version,
            d.upload_date,
            d.approval_status,
            d.extracted_text

        FROM documents d

        JOIN products p
        ON d.product_id = p.product_id
        """)

        ai_df = pd.read_sql(ai_query, conn)

    with st.sidebar.expander("AI Settings"):
        model_labels = list(MODEL_OPTIONS.keys())
        default_model_id = get_default_model_id()
        default_model_label = next(
            (
                label
                for label, model_id in MODEL_OPTIONS.items()
                if model_id == default_model_id
            ),
            model_labels[0],
        )
        selected_model_label = st.selectbox(
            "Bedrock model",
            model_labels,
            index=model_labels.index(default_model_label),
        )
        custom_model_id = st.text_input(
            "Model ID",
            value=MODEL_OPTIONS[selected_model_label],
        )
        region_name = st.text_input(
            "AWS region",
            value=get_default_region(),
        )

    if "ai_chat_messages" not in st.session_state:
        st.session_state.ai_chat_messages = [
            {
                "role": "assistant",
                "content": (
                    "Ask me about uploaded SOPs, document versions, submission records, "
                    "or compliance gaps. I will answer from the records available in this app."
                ),
            }
        ]

    for message in st.session_state.ai_chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Ask a regulatory question")

    if prompt:
        st.session_state.ai_chat_messages.append(
            {"role": "user", "content": prompt}
        )
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking with Amazon Bedrock..."):
                result = ask_bedrock_chatbot(
                    prompt,
                    ai_df,
                    st.session_state.ai_chat_messages[:-1],
                    custom_model_id,
                    region_name,
                )

            st.markdown(result["answer"])
            sources = result.get("sources", [])
            if sources:
                with st.expander("Sources"):
                    for source in sources:
                        page_label = f", page {source['page']}" if source["page"] else ""
                        st.markdown(
                            f"**[{source['citation']}]** "
                            f"{source['document_name']}{page_label} "
                            f"- {source['product_name']}"
                        )
                        st.caption(source["text"][:500])
            if not result["success"]:
                with st.expander("Connection details"):
                    st.code(result["error"] or "No error details returned.")

        st.session_state.ai_chat_messages.append(
            {"role": "assistant", "content": result["answer"]}
        )
        log_audit_event(
            engine,
            current_user,
            "AI_CHAT_QUESTION",
            "ai_assistant",
            None,
            f"Model: {custom_model_id}; Sources: {len(result.get('sources', []))}",
        )

    with st.expander("Document Context Available"):
        if ai_df.empty:
            st.info("No uploaded documents are available for AI context yet.")
        else:
            context_preview_df = ai_df.copy()
            context_preview_df["has_extracted_text"] = (
                context_preview_df["extracted_text"].fillna("").str.len() > 0
            )
            st.dataframe(
                context_preview_df.drop(columns=["extracted_text"]),
                use_container_width=True,
            )

# ================= USER MANAGEMENT (ADMIN ONLY) =================
elif page == "User Management":
    
    if not require_permission("manage_users"):
        st.error("🔒 Access Denied: Only Admins can manage users")
        st.stop()
    
    st.header("👥 User Management")
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "Users List",
        "Create User",
        "Role Reference",
        "Audit Trail",
        "Approval History",
    ])
    
    # TAB 1: USERS LIST
    with tab1:
        st.subheader("All Users")
        
        users_df = get_all_users(engine)
        
        if not users_df.empty:
            # Display users table
            st.dataframe(users_df, use_container_width=True)
            
            st.subheader("User Actions")
            
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown("#### Update User Role")
                user_to_update = st.selectbox(
                    "Select user to update:",
                    users_df['username'].tolist(),
                    key="user_update_select"
                )
                
                selected_user_id = users_df[users_df['username'] == user_to_update]['user_id'].values[0]
                current_role_user = users_df[users_df['username'] == user_to_update]['role'].values[0]
                
                new_role = st.selectbox(
                    "New role:",
                    ["Admin", "RA", "QA"],
                    index=["Admin", "RA", "QA"].index(current_role_user)
                )
                
                if st.button("Update Role", key="update_role_btn"):
                    if update_user_role(engine, selected_user_id, new_role):
                        log_audit_event(
                            engine,
                            current_user,
                            "USER_ROLE_UPDATED",
                            "user",
                            int(selected_user_id),
                            f"{user_to_update}: {current_role_user} -> {new_role}",
                        )
                        st.success(f"User role updated to {new_role}")
                        st.rerun()
                    else:
                        st.error("Failed to update role")
            
            with col2:
                st.markdown("#### Deactivate User")
                user_to_deactivate = st.selectbox(
                    "Select user to deactivate:",
                    users_df[users_df['is_active'] == True]['username'].tolist(),
                    key="user_deactivate_select"
                )
                
                if st.button("Deactivate User", key="deactivate_btn"):
                    selected_user_id = users_df[users_df['username'] == user_to_deactivate]['user_id'].values[0]
                    if deactivate_user(engine, selected_user_id):
                        log_audit_event(
                            engine,
                            current_user,
                            "USER_DEACTIVATED",
                            "user",
                            int(selected_user_id),
                            f"User deactivated: {user_to_deactivate}",
                        )
                        st.success(f"User {user_to_deactivate} deactivated")
                        st.rerun()
                    else:
                        st.error("Failed to deactivate user")
        else:
            st.info("No users found")
    
    # TAB 2: CREATE USER
    with tab2:
        st.subheader("Create New User")
        
        with st.form("create_user_form"):
            new_username = st.text_input("Username")
            new_email = st.text_input("Email")
            new_fullname = st.text_input("Full Name")
            new_password = st.text_input("Password", type="password")
            new_role = st.selectbox("Role", ["Admin", "RA", "QA"])
            
            if st.form_submit_button("Create User"):
                if all([new_username, new_email, new_fullname, new_password]):
                    result = register_user(engine, new_username, new_password, new_email, new_fullname, new_role)
                    if result["success"]:
                        log_audit_event(
                            engine,
                            current_user,
                            "USER_CREATED",
                            "user",
                            None,
                            f"Created {new_username} as {new_role}",
                        )
                        st.success(result["message"])
                    else:
                        st.error(result["message"])
                else:
                    st.warning("Please fill in all fields")
    
    # TAB 3: ROLE REFERENCE
    with tab3:
        st.subheader("Role Permissions Reference")
        
        for role_name, role_info in ROLES.items():
            with st.expander(f"**{role_name}** - {role_info['description']}", expanded=role_name=="Admin"):
                st.markdown(f"**Role:** {role_name}")
                st.markdown(f"**Description:** {role_info['description']}")
                
                st.markdown("**Permissions:**")
                cols = st.columns(2)
                permissions = role_info['permissions']
                
                for idx, perm in enumerate(permissions):
                    with cols[idx % 2]:
                        st.write(f"✓ {perm.replace('_', ' ').title()}")


    # TAB 4: AUDIT TRAIL
    with tab4:
        st.subheader("Audit Trail")
        audit_df = get_audit_trail(engine)
        if audit_df.empty:
            st.info("No audit events recorded yet.")
        else:
            action_filter = st.multiselect(
                "Filter by action",
                sorted(audit_df["action"].dropna().unique()),
                default=sorted(audit_df["action"].dropna().unique()),
            )
            filtered_audit_df = audit_df[audit_df["action"].isin(action_filter)]
            st.dataframe(filtered_audit_df, use_container_width=True)
            st.download_button(
                "Download Audit Trail CSV",
                data=filtered_audit_df.to_csv(index=False),
                file_name=f"audit_trail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
            )

    # TAB 5: APPROVAL HISTORY
    with tab5:
        st.subheader("Approval History")
        approval_history_df = get_approval_history(engine)
        if approval_history_df.empty:
            st.info("No approval workflow records yet.")
        else:
            st.dataframe(approval_history_df, use_container_width=True)
            st.download_button(
                "Download Approval History CSV",
                data=approval_history_df.to_csv(index=False),
                file_name=f"approval_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
            )
