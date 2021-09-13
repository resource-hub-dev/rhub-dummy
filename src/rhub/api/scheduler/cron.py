import logging

from connexion import problem

from rhub.api import db
from rhub.auth.utils import route_require_admin
from rhub.scheduler import model


logger = logging.getLogger(__name__)


@route_require_admin
def list_jobs(user):
    cron_jobs = model.SchedulerCronJob.query.all()
    return [i.to_dict() for i in cron_jobs]


@route_require_admin
def create_job(body, user):
    cron_job = model.SchedulerCronJob.from_dict(body)
    db.session.add(cron_job)
    db.session.commit()
    return cron_job.to_dict()


@route_require_admin
def get_job(cron_job_id, user):
    cron_job = model.SchedulerCronJob.query.get(cron_job_id)
    if not cron_job:
        return problem(404, 'Not Found', f'CronJob {cron_job_id} does not exist')
    return cron_job.to_dict()


@route_require_admin
def update_job(cron_job_id, body, user):
    cron_job = model.SchedulerCronJob.query.get(cron_job_id)
    if not cron_job:
        return problem(404, 'Not Found', f'CronJob {cron_job_id} does not exist')

    cron_job.update_from_dict(body)
    db.session.commit()

    return cron_job.to_dict()


@route_require_admin
def delete_job(cron_job_id, user):
    cron_job = model.SchedulerCronJob.query.get(cron_job_id)
    if not cron_job:
        return problem(404, 'Not Found', f'CronJob {cron_job_id} does not exist')

    db.session.delete(cron_job)
    db.session.commit()
