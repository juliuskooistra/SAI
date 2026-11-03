# The API image. The scheduler runs from the same image with another command
# (docker-compose.yml).

# Use official slim Python image
FROM python:3.12-slim

# uv installs the pinned requirements (much faster than pip, same result)
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies first, so code changes don't
# reinstall everything
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Copy the app (see .dockerignore for what stays out: .env, .venv, tests, ...)
COPY api ./api
COPY scripts ./scripts

# The SQLite file lives here, on a Docker volume (docker-compose.yml)
ENV BIKESHOP_DATA_DIR=/app/api/data

# Set environment variable to get logs immediately
ENV PYTHONUNBUFFERED=1

# Expose port for FastAPI
EXPOSE 8000

# Run FastAPI with Uvicorn, 4 worker processes
CMD ["uvicorn", "api.expose_api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
