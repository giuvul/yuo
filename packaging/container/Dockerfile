# Yuo server image: Debian slim, uv-managed Python, Node for the renderer, ffmpeg and
# espeak-ng as separate programs, non-root, read-only root, data in /data.
# Build from the repository root: docker build -f packaging/container/Dockerfile -t yuo:dev .
#
# Layers are ordered so an update downloads only what changed: the system packages, Python, the Python
# libraries, the voice model, the renderer's libraries and browser each sit in a layer of their own that is
# rebuilt only when its inputs change (the release build keeps its cache in the registry, so unchanged layers
# keep the same digest and `docker compose pull` skips them). Yuo's own code and the web app come last and
# are a few MB.

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

# --- the renderer's libraries and its headless Chromium (only package-lock.json changes them) ---------------
FROM ${NODE_IMAGE} AS renderer
WORKDIR /opt/yuo/renderer
COPY renderer/package.json renderer/package-lock.json ./
# the binary is chrome-headless-shell on x64 and headless_shell in the arm64 build
RUN npm ci --ignore-scripts --no-audit --no-fund \
 && node -e "import('@remotion/renderer').then(r => r.ensureBrowser())" \
 && chrome="$(find node_modules/.remotion -type f \( -name chrome-headless-shell -o -name headless_shell \) | head -n 1)" \
 && test -n "$chrome" && ln -s "/opt/yuo/renderer/$chrome" /opt/yuo/renderer/chrome-headless-shell

# --- Python and the libraries Yuo uses (only the locked dependencies change them, not Yuo's version) -------
FROM ${BASE_IMAGE} AS python
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_INSTALL_DIR=/opt/python UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
RUN uv python install 3.14 && uv venv --python 3.14 /opt/yuo/.venv
WORKDIR /src

# uv.lock also names Yuo's own version: the exported list leaves Yuo out, so a new release alone keeps the
# libraries' layer (COPY compares contents)
FROM python AS lock
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project -o /requirements.txt

FROM python AS pylibs
COPY --from=lock /requirements.txt /requirements.txt
RUN uv pip install --python /opt/yuo/.venv --require-hashes --no-deps -r /requirements.txt

# --- the voice model (only its pinned hashes change it) ---------------------------------------------------
FROM python AS models
COPY yuo/adapters/tts/kokoro_models.py /src/kokoro_models.py
RUN /opt/yuo/.venv/bin/python /src/kokoro_models.py /opt/yuo/models

# --- Yuo itself, kept apart from its libraries ----------------------------------------------------------------
FROM pylibs AS app
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY yuo/ ./yuo/
RUN uv pip install --python /opt/yuo/.venv --no-deps . \
 && site=/opt/yuo/.venv/lib/python3.14/site-packages && mkdir -p /opt/app/site /opt/app/bin \
 && cp -a "$site/yuo" "$site"/yuo-*.dist-info /opt/app/site/ && cp -a /opt/yuo/.venv/bin/yuo /opt/app/bin/

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
COPY --from=pylibs /opt/yuo/.venv /opt/yuo/.venv
COPY --from=models /opt/yuo/models /opt/yuo/models
COPY --from=renderer /opt/yuo/renderer /opt/yuo/renderer
# what changes with every release
COPY renderer/ /opt/yuo/renderer/
COPY --from=app /opt/app/site/ /opt/yuo/.venv/lib/python3.14/site-packages/
COPY --from=app /opt/app/bin/yuo /opt/yuo/.venv/bin/yuo
COPY --from=web /src/web/dist /opt/yuo/web
COPY LICENSE NOTICE THIRD_PARTY_LICENSES /opt/yuo/
# release builds name their update feed and their image (release.yml): a build without a feed never looks for
# updates, and the image name lets Settings > Updates give the exact YUO_IMAGE line to set
ARG YUO_UPDATE_FEED=
ARG YUO_IMAGE_REPO=
ENV PATH=/opt/yuo/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp \
    YUO_DATA_DIR=/data YUO_CLI_HOME=/data/home YUO_HOST=0.0.0.0 YUO_PORT=18765 \
    YUO_WEB_DIR=/opt/yuo/web YUO_RENDERER_DIR=/opt/yuo/renderer YUO_KOKORO_DIR=/opt/yuo/models \
    YUO_CHROME=/opt/yuo/renderer/chrome-headless-shell YUO_SECRETS_KEY_FILE=/run/secrets/yuo_key \
    YUO_UPDATE_FEED=${YUO_UPDATE_FEED} YUO_IMAGE_REPO=${YUO_IMAGE_REPO}
USER yuo
VOLUME /data
EXPOSE 18765
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:18765/api/health', timeout=4)"]
ENTRYPOINT ["tini", "--", "yuo"]
CMD ["serve"]
