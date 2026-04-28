# Two image variants are built from this Dockerfile:
#   Public (default):  docker build .
#   Infra (paid):      docker build --build-arg INSTALL_INFRA_EXTRAS=true .
# The infra image installs aioboto3 so the Kinesis event publisher works
# when ENABLE_EVENT_PUBLISHING=true is set in the container environment.
# The OSS image never installs aioboto3.
#
# VITE_ENABLE_AUTOMATIONS=true is accepted as a backward-compat alias for
# INSTALL_INFRA_EXTRAS=true so the existing docker-publish.yml workflow
# keeps producing a working infra image. Drop the alias once the workflow
# build-arg is renamed.
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
ARG INSTALL_INFRA_EXTRAS=
ARG VITE_ENABLE_AUTOMATIONS=
LABEL org.opencontainers.image.version="${VERSION}"
LABEL org.opencontainers.image.title="Initiative"
LABEL org.opencontainers.image.description="Initiative project management application"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
COPY backend/requirements-infra.txt ./requirements-infra.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_INFRA_EXTRAS" = "true" ] || [ "$VITE_ENABLE_AUTOMATIONS" = "true" ]; then \
         pip install --no-cache-dir -r requirements-infra.txt; \
       fi
COPY backend/ .
COPY VERSION ./VERSION
COPY CHANGELOG.md ./CHANGELOG.md
COPY --from=frontend-build /frontend/dist ./static
RUN apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /app/uploads
COPY backend/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["sh", "start.sh"]
