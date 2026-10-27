# Inklight — local document agent.
# Build: docker build --build-arg INKLIGHT_COMMIT=$(git rev-parse HEAD) -t inklight .
# Run:   docker run --rm -p 8765:8765 -v "$PWD/docs:/data" -v inklight-home:/home/inklight/.inklight inklight
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    INKLIGHT_HOME=/home/inklight/.inklight

RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 inklight

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
# Inside a container the server must listen on all interfaces; the Host allow-list still applies,
# so publish the port to localhost only (-p 127.0.0.1:8765:8765) or set INKLIGHT_SERVER_TOKEN.
ENV INKLIGHT_ALLOWED_HOSTS=localhost,127.0.0.1
ENTRYPOINT ["inklight"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765", "--no-open"]
