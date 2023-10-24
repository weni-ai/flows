# syntax = docker/dockerfile:1

ARG PYTHON_VERSION="3.9"
ARG DEBIAN_VERSION="bookworm"
ARG POETRY_VERSION="1.1.15"
ARG REQUESTS_VERSION="2.29.0"

ARG BUILD_DEPS="\
  gcc bzip2 git curl libpq-dev gettext \
  libgdal-dev python3-cffi python3-gdal \
  python3-dev default-libmysqlclient-dev build-essential \
  build-essential \
  git cmake \
  autoconf pkg-config autoconf libtool automake \
  libmariadb-dev npm"
# default-libmysqlclient-dev
ARG RUNTIME_DEPS="\
  git \
  tzdata \
  postgresql-client \
  netcat-traditional \
  curl \
  gosu \
  npm"
#libmariadb3 \

FROM python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION} as base

ARG POETRY_VERSION
ARG REQUESTS_VERSION
ARG NODE_VERSION

ENV PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  DEBIAN_FRONTEND=noninteractive \
  PROJECT=rapidpro \
  PROJECT_PATH=/app \
  PROJECT_USER=rapidpro \
  PROJECT_GROUP=rapidpro \
  NPM_CONFIG_PREFIX=/opt/npm-globals \
  PIP_DISABLE_PIP_VERSION_CHECK=1 \
  PATH="${NPM_CONFIG_PREFIX}/bin:${PATH}:/install/bin"

ARG COMPRESS_ENABLED
ARG BRANDING_ENABLED
 
ARG RAPIDPRO_APPS_GIT_URL
ARG RAPIDPRO_APPS_GIT_BRANCH

LABEL app=${VERSION} \
  os="debian" \
  os.version="12" \
  name="Flows" \
  description="APP image" \
  maintainer="https://github.com/weni-ai" \
  org.opencontainers.image.url="https://github.com/weni-ai/flows" \
  org.opencontainers.image.documentation="https://github.com/weni-ai/flows" \
  org.opencontainers.image.source="https://github.com/weni-ai/flows" \
  org.opencontainers.image.title="Flows"

RUN addgroup --gid 1999 "${PROJECT_GROUP}" \
  && useradd --system -m -d /app -u 1999 -g 1999 "${PROJECT_USER}"

WORKDIR "${PROJECT_PATH}"

RUN rm -f /etc/apt/apt.conf.d/docker-clean; echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

FROM base as build-poetry

ARG POETRY_VERSION
ARG REQUESTS_VERSION
ARG NODE_VERSION

COPY pyproject.toml poetry.lock docker/pip-requires.txt .

RUN --mount=type=cache,mode=0755,target=/pip_cache,id=pip pip install --cache-dir /pip_cache -U poetry=="${POETRY_VERSION}" \
  && poetry cache clear -n --all pypi \
  && pip install --cache-dir /pip_cache requests=="${REQUESTS_VERSION}" \
  && poetry add -n --lock $(cat pip-requires.txt) \
  && poetry export --without-hashes --output requirements.txt

FROM base as build

ARG BUILD_DEPS

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt,sharing=locked \
  apt-get update \
  && apt-get install --no-install-recommends --no-install-suggests -y ${BUILD_DEPS}
 
COPY --from=build-poetry /app/requirements.txt /tmp/dep/
RUN --mount=type=cache,mode=0755,target=/pip_cache,id=pip pip install --cache-dir /pip_cache --prefix=/install -r /tmp/dep/requirements.txt

FROM base

ARG BUILD_DEPS
ARG RUNTIME_DEPS

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt,sharing=locked \
  apt-get update \
  && SUDO_FORCE_REMOVE=yes apt-get remove --purge -y ${BUILD_DEPS} \
  && apt-get autoremove -y \
  && apt-get install -y --no-install-recommends ${RUNTIME_DEPS} \
  && rm -rf /usr/share/man /usr/share/doc

COPY --from=build /install /usr/local
COPY --chown=${PROJECT_USER}:${PROJECT_GROUP} . $PROJECT_PATH

RUN --mount=type=cache,id=npm,target=/npm_cache \
  npm install --global --cache /npm_cache \
  coffeescript \
  less \
  yarn \
  && npm install --cache /npm_cache \
  && ln -s "${PROJECT_PATH}/temba/settings.py.prod" "${PROJECT_PATH}/temba/settings.py"

USER "${PROJECT_USER}:${PROJECT_USER}"
EXPOSE 8001
ENTRYPOINT ["bash", "./docker/start"]
CMD ["start"]
