# Production runtime: Python 3.14 (Alpine) is the supported target. Local dev may
# use 3.12+, but run the test suite on 3.14 too so dev and prod stay in parity.
FROM python:3.14-alpine

# Set environment variables to optimize Python for Docker
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# UID/GID from .env (default 1000)
ARG PUID=1000
ARG PGID=1000

# Set the working directory inside the container
WORKDIR /app

# tzdata: IANA timezone database required by stdlib zoneinfo. The ICS export
# resolves ZoneInfo(EVENT_TIMEZONE) at import time; Alpine ships no system zone
# database, so without this the bot fails to start with ZoneInfoNotFoundError.
RUN apk add --no-cache tzdata

# requirements.txt copied first so this layer is cached unless dependencies change.
COPY requirements.txt .
RUN apk add --no-cache --virtual .build-deps \
        build-base \
        libffi-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apk del .build-deps

# Copy the source code from the bot/ directory to /app
COPY bot/ .

# Create app user with host UID/GID and data directory
RUN addgroup -g "$PGID" appuser && \
    adduser -u "$PUID" -G appuser -D appuser && \
    mkdir -p /app/data && \
    chown -R "$PUID:$PGID" /app

USER appuser

CMD ["python", "bot.py"]
