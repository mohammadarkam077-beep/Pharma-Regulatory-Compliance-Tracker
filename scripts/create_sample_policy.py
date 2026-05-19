from utils.database import get_engine, get_database_path
from utils.sop_engine import create_policy, add_policy_step, get_policies, get_policy_steps

e = get_engine()
print('DB:', get_database_path())
create_policy(e, 'Sample SOP: QA Review for New Registrations', 'SOP to QA new imported products', None, None, None)
ps = get_policies(e)
print('Policies:', ps.to_dict('records'))
pid = int(ps[ps['name'] == 'Sample SOP: QA Review for New Registrations']['policy_id'].iloc[0])
add_policy_step(e, pid, 1, 'Initial Document Review', 'QA', 2, 'Review documents for completeness')
add_policy_step(e, pid, 2, 'Safety Assessment', 'Safety', 3, 'Perform basic safety check')
steps = get_policy_steps(e, pid)
print('Steps:', steps.to_dict('records'))
