FROM python:3.12-slim

# Install system dependencies for healthcheck
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONPATH=/app
ARG PORT=5000
ENV PORT=${PORT}

EXPOSE ${PORT}

# Run gunicorn with configurable port
CMD gunicorn --bind 0.0.0.0:${PORT} --workers 4 --timeout 30 --log-level=info app:app