# ---- stage 1: build frontend ----
FROM node:20-alpine AS frontend
# 国内网络构建慢/失败时可传 --build-arg NPM_REGISTRY=https://registry.npmmirror.com
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm config set registry $NPM_REGISTRY && npm ci
COPY frontend/ ./
RUN npm run build

# ---- stage 2: backend + static + migrations ----
FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/scripts ./scripts
COPY backend/docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
COPY --from=frontend /app/dist ./static
ENV STATIC_DIR=/app/static
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
