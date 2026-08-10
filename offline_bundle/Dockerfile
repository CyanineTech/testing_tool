FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY service /app/service
COPY scripts /app/scripts

WORKDIR /app/service
CMD ["python", "/app/service/web_service.py"]
