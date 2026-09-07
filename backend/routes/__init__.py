from routes.worker import worker_bp
from routes.jobs import jobs_bp

API_BLUEPRINTS = [
    jobs_bp,
]

WORKER_BLUEPRINTS = [
    worker_bp,
]
