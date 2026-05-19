# Smart Compliance Alerts Guide

## Overview
The Smart Compliance Alerts system automatically monitors your regulatory compliance across all products and flags issues that require attention.

## Alert Types

### 1. 🔴 **Missing Documents** (High Severity)
- **What it detects**: Required regulatory documents that haven't been uploaded
- **Examples**: CTD, CTA Form, Safety Report, SOPs, Certificate of Analysis
- **Action**: Upload the missing documents
- **Configured for**: Pharmaceutical products
- **Customization**: Edit `REQUIRED_DOCUMENTS` in `utils/compliance_alerts.py`

### 2. 🟡 **Outdated SOPs** (Medium/High Severity)
- **What it detects**: Standard Operating Procedures (SOPs) that haven't been updated
- **Update Cycle**: 12 months (configurable)
- **Severity**:
  - Medium: 12-18 months old
  - High: More than 18 months old
- **Action**: Review and update the SOP
- **Customization**: Change `SOP_UPDATE_FREQUENCY` in `utils/compliance_alerts.py`

### 3. 🔴 **Overdue Renewals** (Critical/High/Medium Severity)
- **What it detects**: Product renewals that are overdue or coming due soon
- **Severity**:
  - Critical: Renewal date has passed
  - High: Due within 30 days
  - Medium: Due within 90 days (configurable warning period)
- **Action**: Submit renewal documentation immediately
- **Customization**: Change `RENEWAL_WARNING_DAYS` in `utils/compliance_alerts.py`

## How to Use

### Dashboard View
1. Open the app and go to **Dashboard**
2. Scroll to **🚨 Smart Compliance Alerts** section
3. View alert summary metrics:
   - Critical Alerts count
   - Missing Documents count
   - Outdated SOPs count
   - Overdue Renewals count
4. Filter by severity level
5. See individual alerts with:
   - Alert type and product name
   - Specific message
   - Recommended action

### Dedicated Alerts Page
1. Click **Smart Compliance Alerts** in the navigation menu
2. View comprehensive alert dashboard with:
   - Alert overview (total, by severity)
   - Multi-filter options (type and severity)
   - Expandable alert details
   - Statistical charts
   - CSV export option

### Filter Options
- **By Alert Type**: Missing Documents, Outdated SOPs, Renewal Due Soon, Overdue Renewal
- **By Severity**: Critical, High, Medium, Low

### Export Alerts
- Click **"📥 Download Alerts as CSV"** to export current alerts
- Use for reporting, email notifications, or integration with other systems

## Severity Levels

| Severity | Color | Icon | Meaning |
|----------|-------|------|---------|
| Critical | Red | 🔴 | Immediate action required |
| High | Orange | 🟠 | Action required soon |
| Medium | Yellow | 🟡 | Plan action |
| Low | Green | 🟢 | For information |

## Configuration

### Customizing Alert Rules

Edit `utils/compliance_alerts.py`:

```python
# Update required documents by product type
REQUIRED_DOCUMENTS = {
    "pharmaceutical": [
        "CTD",
        "CTA Form",
        # Add more as needed...
    ],
    "medical_device": [...],
    "biologics": [...]
}

# Change SOP review frequency (in months)
SOP_UPDATE_FREQUENCY = 12

# Change renewal alert period (in days)
RENEWAL_WARNING_DAYS = 90
```

## Database Requirements

The system uses these database tables:
- **products**: product_id, product_name, country, etc.
- **documents**: doc_id, product_id, document_name, document_type, upload_date, version
- **submissions**: submission_id, product_id, renewal_due_date, submission_status

## Common Scenarios

### Resolving Missing Document Alert
1. Go to **Documents** page
2. Select the product
3. Select document type
4. Upload the required document
5. Alert automatically clears on next page refresh

### Resolving Outdated SOP Alert
1. Download current SOP from **Documents** page
2. Review and update the document
3. Go to **Documents** page and upload new version
4. Alert will clear when version is recent enough

### Resolving Overdue Renewal Alert
1. Go to **Submissions** page
2. Prepare renewal submission
3. Update submission status to "Approved"
4. Alert will clear when date passes

## Tips

- ✅ Review alerts regularly (daily recommended)
- ✅ Set up email notifications for Critical alerts
- ✅ Export alerts monthly for compliance reporting
- ✅ Keep SOP versions up to date
- ✅ Upload required documents as soon as available
- ⚠️ Don't ignore Critical and High severity alerts

## Troubleshooting

**Alerts not showing**: Ensure documents have valid upload_date in database
**Alert won't clear**: Refresh page or check database for recent updates
**Missing alert type**: Verify required documents are configured for your product type
