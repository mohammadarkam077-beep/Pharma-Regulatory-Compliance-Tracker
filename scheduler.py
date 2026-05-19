"""Simple scheduler to run nightly compliance checks and escalations.
Run this as a background process or schedule with OS task scheduler.
"""
from datetime import datetime
import os
import logging
from apscheduler.schedulers.blocking import BlockingScheduler

from utils.database import get_engine
from utils.compliance_alerts import run_scheduled_compliance_checks
from utils.compliance_workflow import escalate_stale_alerts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

engine = get_engine()


def nightly_jobs():
    logger.info("Running nightly compliance checks: %s", datetime.now().isoformat())
    try:
        results = run_scheduled_compliance_checks(engine)
        logger.info("Scheduled checks results: %s", results)
    except Exception as e:
        logger.exception("Error running scheduled checks: %s", e)

    try:
        escalated = escalate_stale_alerts(engine, days_threshold=int(os.getenv('ESCALATE_DAYS', '7')))
        logger.info("Escalated %d alerts", escalated)
    except Exception as e:
        logger.exception("Error running escalation: %s", e)


if __name__ == '__main__':
    sched = BlockingScheduler()
    # Schedule to run nightly at 02:00 AM
    sched.add_job(nightly_jobs, 'cron', hour=2, minute=0)
    logger.info("Starting scheduler... Next run scheduled.")
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
