from utils.database import get_engine
from sqlalchemy import text
from utils.fda_loader import create_submission_for_product
from utils.sop_engine import create_policy, add_policy_step, assign_policy_to_submission

engine = get_engine()
regs = ['ANDA123456','ANDA654321']
product_map = {}
submission_map = {}
with engine.connect() as conn:
    for r in regs:
        row = conn.execute(text("SELECT product_id, product_name FROM products WHERE registration_no = :reg"), {'reg': r}).fetchone()
        if row:
            product_map[r] = {'product_id': row['product_id'], 'product_name': row['product_name']}

# Create submissions for each product
for reg, p in product_map.items():
    sid = create_submission_for_product(engine, p['product_id'])
    submission_map[reg] = sid

# Create a sample SOP policy
policy_name = 'Sample SOP: QA Review for New Registrations'
create_policy(engine, policy_name, 'Auto-generated policy for imported FDA products', None, None, 'New Registration')
# fetch policy id
policy_id = None
with engine.connect() as conn:
    row = conn.execute(text("SELECT policy_id FROM sop_policies WHERE name = :name"), {'name': policy_name}).fetchone()
    if row:
        policy_id = int(row['policy_id'])

# Add steps if policy exists
if policy_id:
    add_policy_step(engine, policy_id, 1, 'Initial QA Review', 'QA', 3, 'Perform initial QA review of submission package')
    add_policy_step(engine, policy_id, 2, 'RA Approval', 'RA', 2, 'Regulatory approval for submission')

# Assign policy to created submissions
assignments = []
if policy_id:
    for reg, sid in submission_map.items():
        if sid:
            pid = product_map[reg]['product_id']
            created = assign_policy_to_submission(engine, policy_id, sid, pid)
            assignments.append({'reg': reg, 'submission_id': sid, 'created_steps': created})

# Summary
print('products_found=', product_map)
print('submissions_created=', submission_map)
print('policy_id=', policy_id)
print('assignments=', assignments)
