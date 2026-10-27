# Inklight — document workspace.
# Build: docker build --build-arg INKLIGHT_COMMIT=$(git rev-parse HEAD) -t inklight .
#
# Private workspace (one library shared by everyone with the token; the container listens on its own network, so a
# token is required). Documents and models are kept in volumes:
#   docker run --rm -p 127.0.0.1:8765:8765 -e INKLIGHT_SERVER_TOKEN=<token> \
#     -v inklight-home:/home/inklight/.inklight -v inklight-models:/home/inklight/.cache inklight
# Public demo (a temporary library per visitor; nothing persists):
#   docker run --rm -p 127.0.0.1:8765:8765 --tmpfs /tmp -v inklight-models:/home/inklight/.cache \
#     inklight serve --host 0.0.0.0 --demo --no-open --public-url https://demo.example.org/
# With HTTPS behind a reverse proxy: docs/deploy/ and docs/HOSTING.md.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    INKLIGHT_HOME=/home/inklight/.inklight

RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 inklight \
    && mkdir -p /home/inklight/.inklight /home/inklight/.cache && chown -R inklight /home/inklight

WORKDIR /app
COPY pyproject.toml hatch_build.py README.md LICENSE NOTICE THIRD_PARTY_LICENSES.md ./
COPY src ./src
# .git is not in the build context; the commit comes in as a build argument (shown by `inklight --version`)
ARG INKLIGHT_COMMIT=""
RUN INKLIGHT_BUILD_COMMIT="$INKLIGHT_COMMIT" pip install .

USER inklight
# Models are fetched at runtime under their own licenses (see THIRD_PARTY_LICENSES.md); mount a volume to keep them.
ENV HF_HOME=/home/inklight/.cache/huggingface
EXPOSE 8765
# Inside a container the server listens on all interfaces. Browsers are accepted for localhost only, unless
# --public-url (or INKLIGHT_PUBLIC_URL) names the address visitors open.
ENV INKLIGHT_ALLOWED_HOSTS=localhost,127.0.0.1
ENTRYPOINT ["inklight"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765", "--no-open"]
