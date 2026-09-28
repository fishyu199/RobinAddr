FROM python:3.12-slim
WORKDIR /app
COPY apps/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY . /app
ENV PYTHONPATH=/app:/app/apps/api
CMD ["sh", "-c", "alembic -c apps/api/alembic.ini upgrade head && exec uvicorn robincop_api.main:app --host 0.0.0.0 --port 8000"]
