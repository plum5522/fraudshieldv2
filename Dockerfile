# Production image for the FraudShield v2 API.
# Same Python minor version the model was trained with (pinned scikit-learn needs it).
FROM python:3.13-slim

# Links the published image on ghcr.io to this repository.
LABEL org.opencontainers.image.source="https://github.com/plum5522/fraudshieldv2"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# Dependencies first: this layer is cached and only rebuilt when requirements change,
# so a code-only change rebuilds in seconds.
COPY requirements.txt .
RUN pip install -r requirements.txt

# The app and the trained model (baked in: no download at startup, no version mismatch).
COPY app ./app
COPY models/scam_clf.joblib ./models/scam_clf.joblib

# Never run as root inside the container.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# --proxy-headers: behind Azure's ingress, trust X-Forwarded-For so request.client.host is
# the real user's IP (the rate limiter needs it). Safe only because the container is
# reachable solely through that ingress.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
