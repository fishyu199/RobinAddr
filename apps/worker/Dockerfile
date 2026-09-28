FROM python:3.12-slim
WORKDIR /app
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY . /app
ENV PYTHONPATH=/app:/app/apps/api
CMD ["sh", "-c", "exec celery -A robincop_api.celery_app:celery_app worker --loglevel=INFO --pool=threads --concurrency=${WORKER_CONCURRENCY:-1}"]
