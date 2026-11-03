"""
Logs and metrics (SPEC §10.3).

- JSON logs: one line per event on stdout, tracebacks folded into the same
  line, so a log system (Loki, Azure's log stream) sees one event per error.
  Copied from kooistra-logging 0.3.0 (`JsonFormatter`, `setup_logging`).
- Prometheus metrics at /metrics:
    http_requests_total, http_request_duration_seconds   counted in the API
        (names as in kooistra-logging; it uses prometheus-fastapi-instrumentator,
        this is a small middleware instead, so it reads in one file)
    job_last_run_timestamp_seconds, job_last_run_ok,
    job_last_success_timestamp_seconds                   read from JobRun
        (the last name as in kooistra-jobs, so its staleness alert fits)
    job_queue_jobs{kind,status}                          read from job_queue

Why read the worker's facts from the database? On the VM the worker is its own
container, and its counters would never reach the API's /metrics. The database
is shared, so reading it at scrape time is right wherever the work ran.

The API's own counters: 4 uvicorn workers each count their share. With
PROMETHEUS_MULTIPROC_DIR set (scripts/start.sh does it), they write to files in
that folder and /metrics adds them up.
"""
import json
import logging
import os
import socket
import sys
import time
import traceback
from datetime import datetime, timezone

from prometheus_client import (
    CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest, REGISTRY,
)
from prometheus_client.core import GaugeMetricFamily
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# ============================================================== logging

class JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line (copied from kooistra-logging)."""

    RESERVED = {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }

    def __init__(self, service: str, environment: str = "prod"):
        super().__init__()
        self.service = service
        self.environment = environment
        self.hostname = socket.gethostname()

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service,
            "environment": self.environment,
            "host": self.hostname,
        }
        if record.pathname:
            payload["source"] = f"{record.module}:{record.funcName}:{record.lineno}"
        if record.exc_info:
            exc_type, exc_value, exc_tb = record.exc_info
            payload["exception"] = {
                "type": exc_type.__name__ if exc_type else None,
                "message": str(exc_value) if exc_value else None,
                "traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
            }
        # Anything passed as logging's extra={...} becomes a field
        for key, value in record.__dict__.items():
            if key not in self.RESERVED and not key.startswith("_"):
                try:
                    json.dumps(value)
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(service: str, level: str | None = None) -> None:
    """Send every log record, uvicorn's included, to stdout as one JSON line."""
    level = level or os.environ.get("LOG_LEVEL", "INFO")
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service=service, environment=os.environ.get("ENVIRONMENT", "prod")))
    root.addHandler(handler)
    for noisy in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        lg = logging.getLogger(noisy)
        lg.handlers = []
        lg.propagate = True
        lg.setLevel(level)
    logging.captureWarnings(True)


# ============================================================== metrics

_MULTIPROC = bool(os.environ.get("PROMETHEUS_MULTIPROC_DIR"))

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests", ["handler", "method", "status"])
HTTP_DURATION = Histogram(
    "http_request_duration_seconds", "HTTP request duration", ["handler", "method"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10))

NOT_COUNTED = {"/metrics", "/health"}


def _handler_label(request: Request) -> str:
    """
    The route template (/api/bikes/{bike_id}), so ids don't explode the series.
    Static frontend files are one label, "frontend". Requests turned away before
    routing (e.g. 401 from the auth middleware) are "none".
    """
    scope = request.scope
    if scope.get("route") is None:
        endpoint = scope.get("endpoint")
        return "frontend" if endpoint is not None and endpoint.__class__.__name__ == "StaticFiles" else "none"
    path = request.url.path
    for name, value in scope.get("path_params", {}).items():
        path = path.replace(f"/{value}", f"/{{{name}}}", 1)
    return path


class MetricsMiddleware(BaseHTTPMiddleware):
    """Counts every request and times it, by route template and status group."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        if request.url.path not in NOT_COUNTED:
            handler = _handler_label(request)
            HTTP_REQUESTS.labels(handler, request.method, f"{response.status_code // 100}xx").inc()
            HTTP_DURATION.labels(handler, request.method).observe(time.perf_counter() - start)
        return response


class DatabaseCollector:
    """
    The worker's facts, read from the shared database at scrape time:
      job_queue_jobs{kind,status}            jobs in the queue
      job_last_run_timestamp_seconds{job}    when a periodic job last ran (JobRun)
      job_last_run_ok{job}                   1 if that run succeeded, else 0
      job_last_success_timestamp_seconds{job} the same time, only if it succeeded
    """

    def collect(self):
        from sqlmodel import Session, func, select
        from .database import engine
        from .models.models import Job, JobRun
        queue = GaugeMetricFamily("job_queue_jobs", "Jobs in the queue by kind and status", labels=["kind", "status"])
        last_run = GaugeMetricFamily("job_last_run_timestamp_seconds", "Unix time the job last ran", labels=["job"])
        last_ok = GaugeMetricFamily("job_last_run_ok", "1 if the job's last run succeeded", labels=["job"])
        last_success = GaugeMetricFamily("job_last_success_timestamp_seconds",
                                         "Unix time the job last succeeded (if its last run did)", labels=["job"])
        try:
            with Session(engine) as db:
                for kind, status, n in db.exec(select(Job.kind, Job.status, func.count()).group_by(Job.kind, Job.status)):
                    queue.add_metric([kind, status], n)
                for run in db.exec(select(JobRun)):
                    ts = run.last_run_at.timestamp()
                    last_run.add_metric([run.name], ts)
                    last_ok.add_metric([run.name], 1 if run.last_ok else 0)
                    if run.last_ok:
                        last_success.add_metric([run.name], ts)
        except Exception:  # noqa: BLE001 - a scrape must not fail because of the database
            pass
        yield from (queue, last_run, last_ok, last_success)


def metrics_response() -> Response:
    """The /metrics page: all processes added up, plus the queue gauge."""
    if _MULTIPROC:
        from prometheus_client import multiprocess
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        registry = CollectorRegistry()
        registry.register(_DefaultMetrics())
    registry.register(DatabaseCollector())
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)


class _DefaultMetrics:
    """The default registry's metrics, for a single process (tests, local runs)."""

    def collect(self):
        yield from REGISTRY.collect()
