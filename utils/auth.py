import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime
import hashlib
import hmac
import secrets

# Role definitions
ROLES = {
    "Admin": {
        "description": "Full access to all features and user management",
        "permissions": ["view_dashboard", "view_products", "view_submissions", "view_documents", 
                       "view_alerts", "view_expiry", "upload_documents", "edit_products",
                       "edit_submissions", "edit_documents", "manage_users", "view_analytics",
                       "ai_assistant", "approve_submissions", "approve_documents"]
    },
    "RA": {
        "description": "Regulatory Affairs - Submissions, renewals, and compliance",
        "permissions": ["view_dashboard", "view_products", "view_submissions", "view_documents",
                       "view_alerts", "upload_documents", "edit_submissions", "ai_assistant"]
    },
    "QA": {
        "description": "Quality Assurance - Documents, SOPs, and quality control",
        "permissions": ["view_dashboard", "view_products", "view_documents", "view_alerts",
                       "upload_documents", "edit_documents", "view_expiry", "ai_assistant"]
    }
}


def hash_password(password):
    """Hash password using PBKDF2-SHA256."""
    salt = secrets.token_hex(16)
    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode(),
        salt.encode(),
        100_000,
    ).hex()
    return f"pbkdf2_sha256${salt}${password_hash}"


def verify_password(password, hashed):
    """Verify password.

    Supports PBKDF2 hashes, optional bcrypt hashes, and legacy SHA-256 hashes.
    """
    if not hashed:
        return False

    hashed_str = str(hashed)

    if hashed_str.startswith("pbkdf2_sha256$"):
        try:
            _, salt, expected_hash = hashed_str.split("$", 2)
            password_hash = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode(),
                salt.encode(),
                100_000,
            ).hex()
            return hmac.compare_digest(password_hash, expected_hash)
        except ValueError:
            return False

    # Optional support for bcrypt hashes already stored in an existing database.
    if hashed_str.startswith("$2"):
        try:
            import bcrypt
            return bcrypt.checkpw(password.encode(), hashed_str.encode())
        except Exception:
            return False

    # Fallback: legacy SHA-256
    return hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), hashed_str)


def setup_auth_table(engine):
    """Create users table if it doesn't exist"""
    with engine.connect() as conn:
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


def create_default_admin(engine, username="admin", password="admin123"):
    """Create default admin user if none exists"""
    with engine.connect() as conn:
        # Check if admin exists
        result = conn.execute(
            text("SELECT user_id FROM users WHERE username = :username"),
            {"username": username}
        ).fetchone()
        
        if not result:
            hashed_pwd = hash_password(password)
            conn.execute(
                text("""
                INSERT INTO users (username, password, email, role, full_name, created_at, is_active)
                VALUES (:username, :password, :email, :role, :full_name, :created_at, :is_active)
                """),
                {
                    "username": username,
                    "password": hashed_pwd,
                    "email": "admin@regulatory.com",
                    "role": "Admin",
                    "full_name": "System Administrator",
                    "created_at": datetime.now().isoformat(),
                    "is_active": True
                }
            )
            conn.commit()
            return True
        return False


def login_user(engine, username, password):
    """Authenticate user and return user data"""
    with engine.connect() as conn:
        user = conn.execute(
            text("""
            SELECT user_id, username, role, full_name, email
            FROM users
            WHERE username = :username AND is_active = 1
            """),
            {"username": username}
        ).fetchone()
        
        if not user:
            return None
        
        # Verify password
        stored_user = conn.execute(
            text("SELECT password FROM users WHERE username = :username"),
            {"username": username}
        ).fetchone()
        
        if not verify_password(password, stored_user[0]):
            return None
        
        # Update last login
        conn.execute(
            text("UPDATE users SET last_login = :last_login WHERE username = :username"),
            {
                "last_login": datetime.now().isoformat(),
                "username": username
            }
        )
        conn.commit()
        
        return {
            "user_id": user[0],
            "username": user[1],
            "role": user[2],
            "full_name": user[3],
            "email": user[4]
        }


def register_user(engine, username, password, email, full_name, role="QA"):
    """Create new user"""
    if role not in ROLES:
        return {"success": False, "message": "Invalid role"}
    
    try:
        with engine.connect() as conn:
            hashed_pwd = hash_password(password)
            conn.execute(
                text("""
                INSERT INTO users (username, password, email, role, full_name, created_at, is_active)
                VALUES (:username, :password, :email, :role, :full_name, :created_at, :is_active)
                """),
                {
                    "username": username,
                    "password": hashed_pwd,
                    "email": email,
                    "role": role,
                    "full_name": full_name,
                    "created_at": datetime.now().isoformat(),
                    "is_active": True
                }
            )
            conn.commit()
            return {"success": True, "message": f"User {username} created successfully"}
    except Exception as e:
        return {"success": False, "message": f"Error creating user: {str(e)}"}


def get_all_users(engine):
    """Get all users (Admin only)"""
    with engine.connect() as conn:
        query = text("""
        SELECT user_id, username, email, role, full_name, created_at, last_login, is_active
        FROM users
        ORDER BY created_at DESC
        """)
        df = pd.read_sql(query, conn)
        return df


def update_user_role(engine, user_id, new_role):
    """Update user role (Admin only)"""
    if new_role not in ROLES:
        return False
    
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE users SET role = :role WHERE user_id = :user_id"),
            {"role": new_role, "user_id": user_id}
        )
        conn.commit()
        return True


def deactivate_user(engine, user_id):
    """Deactivate user (Admin only)"""
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE users SET is_active = 0 WHERE user_id = :user_id"),
            {"user_id": user_id}
        )
        conn.commit()
        return True


def check_permission(user_role, permission):
    """Check if user has permission"""
    if user_role not in ROLES:
        return False
    return permission in ROLES[user_role]["permissions"]


def get_role_info(role):
    """Get role information"""
    return ROLES.get(role, None)


def initialize_auth_session(engine):
    """Initialize authentication session in Streamlit"""
    # Setup auth table
    setup_auth_table(engine)
    
    # Create default admin if needed
    create_default_admin(engine)
    
    # Initialize session state
    if "user" not in st.session_state:
        st.session_state.user = None
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False


def logout():
    """Logout user"""
    st.session_state.user = None
    st.session_state.authenticated = False
    st.rerun()


def is_authenticated():
    """Check if user is authenticated"""
    return st.session_state.get("authenticated", False)


def get_current_user():
    """Get current logged-in user"""
    return st.session_state.get("user", None)


def get_current_role():
    """Get current user's role"""
    user = get_current_user()
    if user:
        return user.get("role", None)
    return None


def require_role(required_role):
    """Decorator/check to require specific role"""
    current_role = get_current_role()
    if not current_role:
        return False
    return current_role == required_role or current_role == "Admin"


def require_permission(permission):
    """Check if current user has permission"""
    current_role = get_current_role()
    if not current_role:
        return False
    return check_permission(current_role, permission)


def show_login_page(engine):
    """Display login/register page"""
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.title("🔐 Regulatory Compliance Tracker")
        st.markdown("### User Authentication")
        
        tab1, tab2 = st.tabs(["Login", "Register"])
        
        # LOGIN TAB
        with tab1:
            st.subheader("Login")
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            
            if st.button("Login", key="login_button", use_container_width=True):
                if username and password:
                    user = login_user(engine, username, password)
                    if user:
                        st.session_state.user = user
                        st.session_state.authenticated = True
                        st.success(f"Welcome, {user['full_name']}!")
                        st.balloons()
                        st.rerun()
                    else:
                        st.error("Invalid username or password")
                else:
                    st.warning("Please enter username and password")
            
            # Demo credentials
            st.markdown("---")
            st.markdown("**Demo Credentials:**")
            st.info("""
            **Admin**: admin / admin123
            """)
        
        # REGISTER TAB
        with tab2:
            st.subheader("Create New Account")
            new_username = st.text_input("Username", key="reg_username")
            new_email = st.text_input("Email", key="reg_email")
            new_fullname = st.text_input("Full Name", key="reg_fullname")
            new_password = st.text_input("Password", type="password", key="reg_password")
            new_role = st.selectbox("Role", ["QA", "RA"], key="reg_role")
            
            if st.button("Create Account", key="register_button", use_container_width=True):
                if all([new_username, new_email, new_fullname, new_password]):
                    result = register_user(engine, new_username, new_password, new_email, new_fullname, new_role)
                    if result["success"]:
                        st.success(result["message"])
                        st.info("Please login with your new credentials")
                    else:
                        st.error(result["message"])
                else:
                    st.warning("Please fill in all fields")
