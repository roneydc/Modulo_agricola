"""Entrypoint do worker:

    celery -A workers.celery_app worker --loglevel=info --concurrency=2
"""
from workers.tasks import celery  # noqa: F401

app = celery
