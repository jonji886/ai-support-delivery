FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apps ./apps
COPY data ./data
COPY knowledge ./knowledge
# Persisted runtime state (conversations, tickets) is mounted as a volume.
RUN mkdir -p /app/runtime
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
