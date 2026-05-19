import importlib, traceback

try:
    m = importlib.import_module('utils.compliance_alerts')
    print('Loaded module:', m.__file__)
    run_funcs = [n for n in dir(m) if n.startswith('run_')]
    print('run_* members:', run_funcs)
    print('has run_scheduled_compliance_checks:', hasattr(m, 'run_scheduled_compliance_checks'))
except Exception as e:
    traceback.print_exc()
