FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
# 国内 LightHouse 部署：使用阿里云 PyPI 镜像，避免访问官方源超时。
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --timeout 120 -r requirements.txt
COPY apps ./apps
COPY config ./config
COPY data ./data
COPY knowledge ./knowledge
# Persisted runtime state (conversations, tickets) is mounted as a volume.
RUN mkdir -p /app/runtime
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
