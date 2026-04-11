FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENTMEMORY_API_HOST=0.0.0.0 \
    AGENTMEMORY_API_PORT=8765

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY agentmemory ./agentmemory
COPY web ./web

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

EXPOSE 8765

CMD ["python", "-m", "agentmemory.api"]
