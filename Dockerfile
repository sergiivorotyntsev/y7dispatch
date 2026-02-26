# y7dispatch — Vehicle Transport Automation
FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY api/ api/
COPY services/ services/
COPY extractors/ extractors/
COPY core/ core/
COPY models/ models/
COPY schemas/ schemas/
COPY *.yaml .

# Pre-built frontend (npm run build outputs to static/)
COPY static/ static/

# Data directories
RUN mkdir -p data uploads/email data/attachments config logs backups

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
