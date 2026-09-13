# Base stage
FROM python:3.12-slim AS base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV APP_HOME=/app

WORKDIR $APP_HOME

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gettext \
    ffmpeg \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Builder stage
FROM base AS builder

# Install python dependencies
COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# Final stage
FROM base

# Create non-root user
RUN addgroup --system django && adduser --system --group django

# Install dependencies from wheels
COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache /wheels/*

# Copy project files
COPY . $APP_HOME

# Make entrypoint executable
RUN chmod +x $APP_HOME/entrypoint.sh

# Create directories for static/media so collectstatic works
RUN mkdir -p $APP_HOME/staticfiles $APP_HOME/media

# Set ownership
RUN chown -R django:django $APP_HOME

# Switch to non-root user
USER django

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "--config", "gunicorn.conf.py", "dailytaiyari.wsgi:application"]
