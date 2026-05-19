import sqlite3, tempfile, os
from datetime import datetime, timedelta

db_dir = os.path.join(tempfile.gettempdir(), 'regulatory_app')
db_path = os.path.join(db_dir, 'regulatory_app.db')
print('db_path=', db_path)
conn = sqlite3.connect(db_path)
c = conn.cursor()
now = datetime.now().isoformat(timespec='seconds')
# Insert policy
policy_name = 'Sample SOP: QA Review for New Registrations'
try:
    c.execute("INSERT INTO sop_policies (name, description, product_type, country, submission_type, is_active, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
              (policy_name, 'Auto-generated policy for imported FDA products', None, None, 'New Registration', 1, now, now))
    policy_id = c.lastrowid
except Exception as e:
    # Try to find existing
    c.execute('SELECT policy_id FROM sop_policies WHERE name = ?', (policy_name,))
    row = c.fetchone()
    policy_id = row[0] if row else None

if policy_id:
    # Add two steps
    try:
        c.execute('INSERT INTO policy_steps (policy_id, step_order, title, role, due_days, instructions) VALUES (?,?,?,?,?,?)',
                  (policy_id, 1, 'Initial QA Review', 'QA', 3, 'Perform initial QA review'))
        c.execute('INSERT INTO policy_steps (policy_id, step_order, title, role, due_days, instructions) VALUES (?,?,?,?,?,?)',
                  (policy_id, 2, 'RA Approval', 'RA', 2, 'Regulatory approval'))
        conn.commit()
    except Exception as e:
        pass

# Find submissions for our products
regs = ('ANDA123456','ANDA654321')
placeholders = ','.join('?' for _ in regs)
c.execute(f"SELECT submission_id, product_id FROM submissions WHERE product_id IN (SELECT product_id FROM products WHERE registration_no IN ({placeholders}))", regs)
subs = c.fetchall()
print('subs=', subs)
# Fetch steps for policy
c.execute('SELECT step_id, due_days FROM policy_steps WHERE policy_id = ?', (policy_id,))
steps = c.fetchall()
for sub in subs:
    submission_id, product_id = sub
    for step in steps:
        step_id, due_days = step
        due_date = None
        if due_days:
            due_date = (datetime.now() + timedelta(days=due_days)).isoformat(timespec='seconds')
        try:
            c.execute('INSERT INTO policy_assignments (policy_id, submission_id, product_id, step_id, assigned_to, status, due_date, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                      (policy_id, submission_id, product_id, step_id, None, 'Open', due_date, now, now))
        except Exception as e:
            pass
conn.commit()
print('done')
conn.close()
