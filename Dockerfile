FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Apply latest security patches from Debian repositories.
RUN apt-get update && apt-get dist-upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first to improve layer caching.
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy project and install package.
COPY . .
RUN pip install -e .

# Drop root privileges for runtime.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

# Optional runtime knobs (can be overridden at `docker run` time).
ENV WALTER_ENABLE_WEB_DASHBOARD=1 \
    WALTER_WEB_HOST=0.0.0.0 \
    WALTER_WEB_PORT=8765

EXPOSE 8765

CMD ["python", "main.py"]
