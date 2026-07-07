#!/bin/bash
# Test entrypoint used by docker/docker-compose.test.yml.
# Mirrors the CI flow: migrate the PostGIS database, then run the suite with coverage.
set -euo pipefail

cd "${PROJECT_PATH:-/app}"

# The image ships a symlink to settings.py.prod (which requires many production env
# vars). Tests use the dev-based settings, so point settings.py at settings.py.dev,
# matching what CI does.
ln -sf settings.py.dev temba/settings.py

TEST_LABELS="$*"

# coverage is a dev dependency and the image is built with only main deps (poetry export),
# so install it if missing. Invoked as `python -m coverage` (the console script entry
# point misbehaves here).
python -c 'import coverage' 2>/dev/null || pip install --quiet coverage

echo "Running migrations..."
python manage.py migrate --noinput

echo "Running tests: ${TEST_LABELS:-<all>}"
python -m coverage run manage.py test --keepdb --noinput --verbosity=2 ${TEST_LABELS}
python -m coverage report -i
