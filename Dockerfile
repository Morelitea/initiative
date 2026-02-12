FROM node:20-alpine AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN npm install -g pnpm && pnpm install
COPY frontend .
COPY VERSION /VERSION
ARG VITE_API_URL=/api/v1
ARG VITE_VERSION_SUFFIX=
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_VERSION_SUFFIX=$VITE_VERSION_SUFFIX
RUN pnpm run build

FROM python:3.12-slim AS backend-runtime
ARG VERSION=0.1.0
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.title="Initiative"
LABEL org.opencontainers.image.description="Initiative project management application"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt
COPY backend/ .
COPY VERSION ./VERSION
COPY CHANGELOG.md ./CHANGELOG.md
COPY --from=frontend-build /frontend/dist ./static
CMD ["sh", "start.sh"]
