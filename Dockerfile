# ── stage 1: build the Vue SPA ───────────────────────────────────
FROM node:22-alpine AS web-builder
WORKDIR /app/web
COPY web/package.json web/package-lock.json* ./
RUN npm ci --prefer-offline 2>/dev/null || npm install
COPY web ./
RUN npm run build

# ── stage 2: Python API ───────────────────────────────────────────
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    AGENTMEMORY_API_HOST=0.0.0.0 \
    AGENTMEMORY_API_PORT=8765

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY agentmemory ./agentmemory
COPY --from=web-builder /app/web/dist ./web/dist

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

EXPOSE 8765

CMD ["python", "-m", "agentmemory.api"]
