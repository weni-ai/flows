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

ARG RUNTIME_DEPS="\
  tzdata \
  libmariadb3 \
  netcat-traditional \
  curl \
  gosu"

FROM python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION} as base

ARG POETRY_VERSION
ARG REQUESTS_VERSION
ARG NODE_VERSION

ENV PYTHONUNBUFFERED=1 \
  DEBIAN_FRONTEND=noninteractive \
  PROJECT=rapidpro \
  PROJECT_PATH=/app \
  PROJECT_USER=rapidpro \
  PROJECT_GROUP=rapidpro \
  NPM_CONFIG_PREFIX=/opt/npm-globals \
  PATH="${NPM_CONFIG_PREFIX}/bin:${PATH}"

ARG COMPRESS_ENABLED
ARG BRANDING_ENABLED
 
ARG RAPIDPRO_APPS_GIT_URL
ARG RAPIDPRO_APPS_GIT_BRANCH

RUN addgroup --gid 1999 "${PROJECT_GROUP}" \
  && useradd --system -m -d /app -u 1999 -g 1999 "${PROJECT_USER}"

WORKDIR "${PROJECT_PATH}"

FROM base as build-poetry

ARG POETRY_VERSION
ARG REQUESTS_VERSION
ARG NODE_VERSION

COPY pyproject.toml poetry.lock docker/pip-requires.txt .

RUN python -m pip install -U poetry=="${POETRY_VERSION}" \
  && poetry cache clear -n --all pypi \
  && pip install requests=="${REQUESTS_VERSION}" \
  && poetry add -n --lock $(cat pip-requires.txt) \
  && poetry export --without-hashes --output requirements.txt \
  && rm -rf /var/lib/apt/lists/*

FROM base as build

ARG BUILD_DEPS

RUN apt-get update \
  && apt-get install --no-install-recommends --no-install-suggests -y ${BUILD_DEPS}
 
#RUN rm -rf /var/lib/apt/lists/*

COPY --from=build-poetry /app/requirements.txt /tmp/dep/
RUN pip install --no-cache-dir -r /tmp/dep/requirements.txt

COPY --chown=${PROJECT_USER}:${PROJECT_GROUP} . $PROJECT_PATH
#RUN chown -R $PROJECT_USER:$PROJECT_GROUP $PROJECT_PATH

RUN npm install --global \
  coffeescript \
  less \
  yarn \
  && npm install \
  && ln -s "${PROJECT_PATH}/temba/settings.py.prod" "${PROJECT_PATH}/temba/settings.py"

USER ${PROJECT_USER}:${PROJECT_USER}
EXPOSE 8001
ENTRYPOINT ["bash", "./docker/start"]
