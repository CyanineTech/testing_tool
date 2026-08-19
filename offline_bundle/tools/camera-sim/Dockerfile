FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY tools/camera-sim/app/ /app/app/

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8002/health')" || exit 1

CMD ["sh", "-c", "exec uvicorn app.main:asgi --host ${WEB_HOST:-0.0.0.0} --port ${CCTV_SERVICE_PORT:-8002}"]
