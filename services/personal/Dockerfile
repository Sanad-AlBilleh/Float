# The personal service image (Assignment 2 §1a: own Dockerfile, no COPY . ., no secrets, pinned, non-root).
FROM python:3.14.7-slim

# No .pyc files in the image; logs go straight to stdout.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

# Dependencies first, so a code change does not reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app/ ./app/
COPY migrations/ ./migrations/

# The commit this image was built from, reported by GET /health.
ARG GIT_SHA=dev
ENV GIT_SHA=${GIT_SHA} \
    PORT=8000

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin float
USER float

EXPOSE 8000
# Shell form so ${PORT} is read at start; exec makes uvicorn PID 1 so it receives SIGTERM.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --no-access-log
