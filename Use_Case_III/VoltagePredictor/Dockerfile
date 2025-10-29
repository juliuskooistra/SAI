# Use official slim Python image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system build dependencies (only if needed by packages like numpy/pandas)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the rest of your app
COPY . .

# Expose port for FastAPI
EXPOSE 8000

# Set environment variable to get logs immediately
ENV PYTHONUNBUFFERED=1

# Run FastAPI with Uvicorn (adjust if your main file isn't main.py)
CMD ["python3", "api/main.py"]
