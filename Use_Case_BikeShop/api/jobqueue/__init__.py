"""
The job queue (SPEC §5.8): `queue` has the table operations, `handlers` the
work per job kind; `scripts/worker.py` is the process that runs them.
Adapted from AI Beacon's `backend/jobqueue/` (Postgres) for SQLite.
"""
