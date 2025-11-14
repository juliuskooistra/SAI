# Running the backend:

docker build -t peak-voltage-api .
docker run -d --restart unless-stopped -p 8000:8000 --name peakapi peak-voltage-api

## Checking logs
docker logs -f peakapi