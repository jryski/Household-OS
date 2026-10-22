# Anthropic OSS Scanner environment for the public, synthetic-only reference.
# No real household or provider resources belong in this build.
FROM python:3.11-slim-bookworm

WORKDIR /src
COPY . /src

# Install build dependencies while online and leave tests runnable offline.
RUN python -m pip install --no-cache-dir -e . \
    && python -m compileall -q /src/src \
    && python -m unittest discover -s tests -v

# No live endpoints, user data, calendar tokens or production env vars required.
