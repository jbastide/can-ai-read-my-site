# Can AI read my site? — web interface in a small container.
# Build:  docker build -t can-ai-read .
# Run:    docker run --rm -p 8080:8080 can-ai-read      then open http://localhost:8080
FROM python:3.12-slim

LABEL org.opencontainers.image.title="can-ai-read-my-site" \
      org.opencontainers.image.description="Check if AI crawlers can get into a website and read the facts on its pages." \
      org.opencontainers.image.source="https://github.com/jbastide/can-ai-read-my-site" \
      org.opencontainers.image.licenses="MIT"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY can_ai_read ./can_ai_read
RUN pip install --no-cache-dir . && rm -rf /root/.cache

USER 10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)" || exit 1
CMD ["can-ai-read", "serve", "--host", "0.0.0.0", "--port", "8080"]
