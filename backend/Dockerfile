FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2-binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer-cached until requirements change)
# Build context is the repo root, so path is relative to that
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the full repo (relative to build context = repo root)
COPY . .

RUN chmod +x backend/entrypoint.sh

ENV PYTHONPATH=/app

# Run migrations then start uvicorn
CMD ["/bin/sh", "backend/entrypoint.sh"]
