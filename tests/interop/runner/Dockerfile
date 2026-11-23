# The ngquic endpoint for the QUIC interop runner; build from the repository
# root: docker build -f tests/interop/runner/Dockerfile -t ngquic-qns .
FROM ubuntu:24.04 AS build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential ca-certificates cmake git perl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv
WORKDIR /src
COPY . .
RUN uv build --wheel --python 3.12 --out-dir /wheels

FROM martenseemann/quic-network-simulator-endpoint:latest
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /wheels /wheels
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir /wheels/*.whl
COPY tests/interop/peer.py /peer.py
COPY tests/interop/runner/run_endpoint.sh /run_endpoint.sh
RUN chmod +x /run_endpoint.sh
ENTRYPOINT ["/run_endpoint.sh"]
