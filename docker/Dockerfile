# syntax = docker/dockerfile:1

ARG PYTHON_VERSION="3.9"
ARG DEBIAN_VERSION="bookworm"
ARG POETRY_VERSION="1.1.15"
ARG REQUESTS_VERSION="2.29.0"

FROM python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION} as base

ENV PYTHONUNBUFFERED=1 \
  DEBIAN_FRONTEND=noninteractive \
  PROJECT=rapidpro \
  PROJECT_PATH=/app \
  PROJECT_USER=$PROJECT \
  PROJECT_GROUP=$PROJECT_USER \
  PROJECT_CONF=${PROJECT_PATH}-conf \
  NPM_CONFIG_PREFIX=/opt/npm-globals \
  PATH="${NPM_CONFIG_PREFIX}/bin:${PATH}"

ARG COMPRESS_ENABLED
ARG BRANDING_ENABLED
 
ARG RAPIDPRO_APPS_GIT_URL
ARG RAPIDPRO_APPS_GIT_BRANCH

RUN useradd -Ums /bin/bash $PROJECT_USER \
 && usermod -aG adm $PROJECT_USER

USER ${PROJECT_USER}:${PROJECT_USER}

WORKDIR "${PROJECT_PATH}"

FROM base as build-poetry

COPY ./pyproject.toml .
COPY ./poetry.lock .
COPY ./docker/pip-requires.txt .

RUN python -m pip install -U poetry=="${POETRY_VERSION}" \
 && poetry cache clear -n --all pypi \
 && pip install requests=="${REQUESTS_VERSION}" \
 && poetry add -n --lock $(cat pip-requires.txt) \
 && poetry export --without-hashes --output requirements.txt

FROM base as build

RUN apt-get update \
 && apt-get install --no-install-recommends --no-install-suggests -y apt-utils \
 && apt-get install --no-install-recommends --no-install-suggests -y gcc bzip2 git curl nginx libpq-dev gettext \
    libgdal-dev python3-cffi python3-gdal vim

RUN curl -sL https://deb.nodesource.com/setup_12.x | bash - \
 && apt-get install --no-install-recommends --no-install-suggests -y nodejs

RUN rm -rf /var/lib/apt/lists/*

RUN mkdir $PROJECT_PATH \
 && mkdir $PROJECT_CONF \
 && mkdir $NPM_CONFIG_PREFIX \
 && chown -R $PROJECT_USER:$PROJECT_GROUP $PROJECT_PATH \
 && chown -R $PROJECT_USER:$PROJECT_GROUP $NPM_CONFIG_PREFIX

RUN rm /etc/nginx/sites-enabled/default

COPY --from=build-poetry /app/requirements.txt /tmp/dep/
COPY ./docker/pip-freeze.txt /tmp/dep/
COPY ./docker/nginx.site.conf /tmp/
RUN pip install --no-cache-dir -r /tmp/dep/requirements.txt

COPY --chown=${PROJECT_USER}:${PROJECT_GROUP} . $PROJECT_PATH
#RUN chown -R $PROJECT_USER:$PROJECT_GROUP $PROJECT_PATH

RUN npm install --global \
  coffeescript \
  less \
  yarn \
  && npm install \
  && ln -s "${PROJECT_PATH}/temba/settings.py.prod" "${PROJECT_PATH}/temba/settings.py"

EXPOSE 8001
ENTRYPOINT ["sh", "./docker/start"]
