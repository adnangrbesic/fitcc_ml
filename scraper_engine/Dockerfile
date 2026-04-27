# ---------------------------------------------------------------------------
# BuyGuardian Scraper — Production Dockerfile
# Uses the official Microsoft Playwright image (includes Chromium + deps).
# Avoids hours of debugging missing .so libraries on Linux.
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/playwright/python:v1.58.0-jammy

WORKDIR /app

# Copy only dependency metadata first (layer caching)
COPY pyproject.toml ./

# Install Python deps — browser binaries are already in the base image
RUN pip install --no-cache-dir . \
    && pip install --no-cache-dir playwright-stealth

# Copy source code
COPY scraper/ ./scraper/

# Resource limits guidance (set in docker-compose or docker run):
#   --memory=2g --cpus=1.5
# One container with 5-10 async workers > 50 micro-containers.

CMD ["python", "-m", "scraper.main"]
