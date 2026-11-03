# The API image. The worker runs from the same image with another command
# (docker-compose.yml). On Azure, one container runs both, under Litestream
# (APP_MODE=all, scripts/start.sh, SPEC §10.2).

# Use official slim Python image
FROM python:3.12-slim

# uv installs the pinned requirements (much faster than pip, same result)
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv

# Litestream copies the SQLite file to Azure Blob Storage (only with APP_MODE=all)
COPY --from=litestream/litestream:0.5.17 /usr/local/bin/litestream /usr/local/bin/litestream

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies first, so code changes don't
# reinstall everything
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Copy the app (see .dockerignore for what stays out: .env, .venv, tests, ...)
COPY api ./api
COPY scripts ./scripts
COPY frontend ./frontend
COPY docs ./docs
COPY litestream.yml ./litestream.yml

# The SQLite file lives here, on a Docker volume (docker-compose.yml)
ENV BIKESHOP_DATA_DIR=/app/api/data

# The assistant's demand model (SPEC §13.5), trained now, into the image.
# Not in /app/api/data: on a VM the volume is mounted there and would hide it.
# The training is seeded, so every build gives the same model.
ENV BIKESHOP_MODEL_DIR=/app/models
RUN python -m scripts.train_demand_model

# Set environment variable to get logs immediately
ENV PYTHONUNBUFFERED=1

# Expose port for FastAPI
EXPOSE 8000

# Run FastAPI with Uvicorn (UVICORN_WORKERS, default 4); APP_MODE picks the set-up
CMD ["sh", "scripts/start.sh"]
