# Yuo server image: Debian slim, uv-managed Python, Node for the renderer, ffmpeg and
# espeak-ng as separate programs, non-root, read-only root, data in /data.
# Build from the repository root: docker build -f packaging/container/Dockerfile -t yuo:dev .

ARG NODE_IMAGE=node:22.23.1-trixie-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.1
ARG BASE_IMAGE=debian:trixie-slim

FROM ${UV_IMAGE} AS uv

# --- the web app -----------------------------------------------------------------------------------------
FROM ${NODE_IMAGE} AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json web/.npmrc* ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY web/ ./
RUN npm run build

# --- the renderer (Remotion) and its headless Chromium ------------------------------------------------------
FROM ${NODE_IMAGE} AS renderer
WORKDIR /opt/yuo/renderer
COPY renderer/package.json renderer/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY renderer/ ./
RUN node -e "import('@remotion/renderer').then(r => r.ensureBrowser())" \
 && chrome="$(find node_modules/.remotion -name chrome-headless-shell -type f | head -n 1)" \
 && test -n "$chrome" && ln -s "/opt/yuo/renderer/$chrome" /opt/yuo/renderer/chrome-headless-shell

# --- Python, the app and the voice model ------------------------------------------------------------------
FROM ${BASE_IMAGE} AS python
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/yuo/.venv
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
RUN uv python install 3.14 && uv sync --frozen --no-dev --no-install-project
COPY yuo/ ./yuo/
RUN uv sync --frozen --no-dev --no-editable \
 && /opt/yuo/.venv/bin/yuo fetch-models /opt/yuo/models

# --- runtime ----------------------------------------------------------------------------------------------
FROM ${BASE_IMAGE}
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl tini ffmpeg espeak-ng \
      libnss3 libnspr4 libdbus-1-3 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libdrm2 libxkbcommon0 \
      libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2t64 libpango-1.0-0 libcairo2 \
      libxshmfence1 libx11-xcb1 libxcb-dri3-0 libexpat1 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home-dir /data --shell /usr/sbin/nologin yuo \
 && mkdir /data && chown yuo:yuo /data
COPY --from=renderer /usr/local/bin/node /usr/local/bin/node
COPY --from=python /opt/python /opt/python
COPY --from=python /opt/yuo /opt/yuo
COPY --from=renderer /opt/yuo/renderer /opt/yuo/renderer
COPY --from=web /src/web/dist /opt/yuo/web
COPY LICENSE NOTICE THIRD_PARTY_LICENSES /opt/yuo/
ENV PATH=/opt/yuo/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp \
    YUO_DATA_DIR=/data YUO_CLI_HOME=/data/home YUO_HOST=0.0.0.0 YUO_PORT=18765 \
    YUO_WEB_DIR=/opt/yuo/web YUO_RENDERER_DIR=/opt/yuo/renderer YUO_KOKORO_DIR=/opt/yuo/models \
    YUO_CHROME=/opt/yuo/renderer/chrome-headless-shell YUO_SECRETS_KEY_FILE=/run/secrets/yuo_key
USER yuo
VOLUME /data
EXPOSE 18765
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:18765/api/health', timeout=4)"]
ENTRYPOINT ["tini", "--", "yuo"]
CMD ["serve"]
