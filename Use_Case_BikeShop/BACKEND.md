# Running the backend with Docker

The API, the scheduler and the frontend run together with Docker Compose.
The full server set-up is in [DEPLOY.md](DEPLOY.md).

```bash
cp .env.example .env        # fill it in
docker compose up -d --build
docker compose exec api python -m scripts.seed
```

## Checking logs

```bash
docker compose logs -f api          # requests and errors
docker compose logs -f scheduler    # "expired N orders" every 15 minutes
docker compose ps                   # is everything up and healthy?
curl -s localhost:8130/health       # database, inference, scheduler's last run
```

## Running only the API image (as in VoltagePredictor)

```bash
docker build -t bikeshop-api .
docker run -d --restart unless-stopped -p 127.0.0.1:8000:8000 \
  --env-file .env -v bikeshop-data:/app/api/data --name bikeshop bikeshop-api
```

Without `-v bikeshop-data:...`, the database is inside the container and is
gone after the next `docker rm`.
