# Role-Based Access Control (RBAC) Guide

## Overview
The Regulatory Compliance Tracker includes a comprehensive Role-Based Access Control system with three roles: **Admin**, **RA** (Regulatory Affairs), and **QA** (Quality Assurance).

## Roles & Permissions

### 🔴 Admin
**Full system access and user management**

**Permissions:**
- ✓ View Dashboard
- ✓ View & Edit Products
- ✓ View & Edit Submissions
- ✓ View & Edit Documents
- ✓ View Smart Compliance Alerts
- ✓ View Expiry Predictions
- ✓ Use AI Assistant
- ✓ Approve Submissions
- ✓ Manage Users (create, update roles, deactivate)
- ✓ View Analytics

**Responsibilities:**
- Oversee all compliance activities
- Manage user accounts and permissions
- Approve critical submissions
- Generate reports and analytics

---

### 🟠 RA (Regulatory Affairs)
**Submissions, renewals, and compliance tracking**

**Permissions:**
- ✓ View Dashboard
- ✓ View Products
- ✓ View & Edit Submissions
- ✓ View & Upload Documents
- ✓ View Smart Compliance Alerts
- ✓ Use AI Assistant

**Responsibilities:**
- Manage product submissions and renewals
- Track compliance timelines
- Upload regulatory documentation
- Monitor renewal deadlines
- Prepare submission packages

---

### 🟡 QA (Quality Assurance)
**Document management, SOPs, and quality control**

**Permissions:**
- ✓ View Dashboard
- ✓ View Products
- ✓ View & Edit Documents
- ✓ View & Upload Documents
- ✓ View Smart Compliance Alerts
- ✓ View Expiry Predictions
- ✓ Use AI Assistant

**Responsibilities:**
- Manage SOPs and quality documents
- Maintain document versions
- Review quality control records
- Monitor document compliance status
- Handle quality-related alerts

---

## Default Admin Account

**Username:** `admin`  
**Password:** `admin123`

⚠️ **Important:** Change the default admin password on first login!

## Getting Started

### 1. Initial Login
```
1. Enter the application
2. Use default credentials (admin/admin123)
3. Go to "User Management" page
4. Create accounts for RA and QA users
```

### 2. Creating New Users

**As Admin:**
1. Navigate to **User Management** → **Create User** tab
2. Fill in user details:
   - Username (unique)
   - Email
   - Full Name
   - Password
   - Role (Admin/RA/QA)
3. Click **Create User**
4. Share credentials with new user

**User Self-Registration:**
1. On login page, click **Register** tab
2. Fill in signup information
3. Default role: QA
4. Admin can change role later if needed

### 3. Managing Users

**View All Users:**
- Go to **User Management** → **Users List** tab
- See all active and inactive users
- View their roles and login history

**Update User Role:**
1. Go to **User Management** → **Users List** tab
2. Select user from dropdown
3. Choose new role
4. Click **Update Role**

**Deactivate User:**
1. Go to **User Management** → **Users List** tab
2. Select user from dropdown
3. Click **Deactivate User**
4. User cannot login until reactivated by Admin

---

## Role-Based Features

### Dashboard
All roles see:
- Total products count
- Submission status overview
- Expiry risk summary
- Smart Compliance Alerts

**Role-Specific Views:**
- **Admin**: Full analytics and user metrics
- **RA**: Submission and renewal focus
- **QA**: Document and quality focus

### Products Page
**Visible to:** Admin, QA, RA
- **Admin**: Can create and edit products
- **QA**: Can view products
- **RA**: Can view products

### Submissions Page
**Visible to:** Admin, RA
- **Admin**: Full submission management
- **RA**: Create, view, and edit submissions

### Documents Page
**Visible to:** Admin, QA, RA
- **Admin**: Full document management
- **QA**: Upload and manage documents
- **RA**: View and upload documents

### Smart Compliance Alerts
**Visible to:** All roles
- Same alerts for all users
- Role-specific action recommendations

### Expiry Prediction
**Visible to:** Admin, QA
- Track renewal deadlines
- Predict expiry dates

### AI Assistant
**Visible to:** All roles
- Search documents intelligently
- Same search capabilities for all

### User Management
**Visible to:** Admin only
- Create and manage users
- Assign roles
- Deactivate accounts
- View role permissions

---

## Navigation by Role

### 🔴 Admin Navigation
```
Dashboard
├── Smart Compliance Alerts
├── Products
├── Submissions
├── Expiry Prediction
├── Documents
├── AI Assistant
└── User Management
```

### 🟠 RA Navigation
```
Dashboard
├── Smart Compliance Alerts
├── Products
├── Submissions
├── Documents
└── AI Assistant
```

### 🟡 QA Navigation
```
Dashboard
├── Smart Compliance Alerts
├── Products
├── Expiry Prediction
├── Documents
└── AI Assistant
```

---

## Security Best Practices

### Password Management
- ✅ Change default admin password immediately
- ✅ Use strong, unique passwords (12+ characters, mixed case, numbers, symbols)
- ✅ Don't share passwords
- ✅ Update password regularly (every 90 days recommended)

### User Management
- ✅ Review active users regularly
- ✅ Deactivate unused accounts
- ✅ Assign least privilege roles
- ✅ Document access changes

### Audit Trail
- View last login timestamps for each user
- Track user creation dates
- Monitor role changes

---

## Troubleshooting

### Can't Access a Feature?
1. Check your role in the sidebar (e.g., "Role: RA")
2. Verify the feature requires that permission
3. Ask Admin to update your role if needed

### Forgot Password?
- Contact your Admin
- Admin cannot reset passwords directly
- You'll need to create a new account through registration

### Access Denied Error?
```
Error: "🔒 Access Denied: You don't have permission to view [feature]"
```
**Solution:** Your current role doesn't have permission for this feature. Contact Admin to request access.

### Can't Create Users?
- Only Admins can create users
- Non-Admin users can self-register through the Register tab

---

## Frequently Asked Questions

**Q: Can a user have multiple roles?**  
A: No, each user has one primary role. Contact Admin for role changes.

**Q: How do I change my password?**  
A: Currently requires Admin intervention. Feature coming soon.

**Q: What happens if I forget my username?**  
A: Contact your Admin with your email address.

**Q: Can I view audit logs of who did what?**  
A: Last login timestamps are visible to Admins in User Management.

**Q: How often should I review user permissions?**  
A: Monthly recommended, especially after staff changes.

---

## Technical Details

### Authentication
- Passwords are hashed using SHA-256
- Session stored in Streamlit state
- Automatic logout when closing browser
- Last login timestamp tracked

### Permissions System
- Role-based permission mapping in `utils/auth.py`
- Permissions checked at page entry
- Granular permission control possible
- Easy to extend with new permissions

### Database
- Users table stores credentials and role
- User activity tracked with timestamps
- Support for active/inactive status

---

## For Administrators

### Common Admin Tasks

**Add new QA analyst:**
1. Go to User Management
2. Create user with "QA" role
3. Share login credentials
4. User can start uploading documents

**Update RA to Admin:**
1. Go to User Management → Users List
2. Select user
3. Change role to "Admin"
4. User gains full access immediately

**Remove departing employee:**
1. Go to User Management → Users List
2. Select user
3. Click "Deactivate User"
4. User cannot login
5. Their records remain in system for audit

**Review access summary:**
1. Go to User Management
2. View all users and their roles
3. Check last login timestamps
4. Identify inactive accounts

---

## Support & Contact

For access issues or permission questions, contact your System Administrator.
