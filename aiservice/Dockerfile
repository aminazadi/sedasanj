# syntax=docker/dockerfile:1.7
FROM python:3.11-slim-bookworm AS python-builder

ARG PIP_INDEX_URL=https://mirror.novin.cloud/artifactory/api/pypi/pypi/simple/
ARG PIP_EXTRA_INDEX_URL=
ARG PIP_DEFAULT_TIMEOUT=600
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG TARGETARCH
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT} \
    PIP_RETRIES=15 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CMAKE_BUILD_PARALLEL_LEVEL=4

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
COPY requirements-runtime.txt requirements-build.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/venv \
    && if [ "${TARGETARCH}" = "arm64" ]; then \
         export CMAKE_ARGS="-DGGML_NATIVE=OFF"; \
       fi \
    && mkdir -p /tmp/torch-wheel \
    && /opt/venv/bin/python -m pip download --no-deps --only-binary=:all: \
       --retries 15 --timeout "${PIP_DEFAULT_TIMEOUT}" --dest /tmp/torch-wheel \
       --index-url "${TORCH_INDEX_URL}" torch==2.7.1+cpu \
    && /opt/venv/bin/python -m pip install \
       --retries 15 --timeout "${PIP_DEFAULT_TIMEOUT}" /tmp/torch-wheel/torch-*.whl \
    && rm -rf /tmp/torch-wheel \
    && /opt/venv/bin/python -m pip install \
       --retries 15 --timeout "${PIP_DEFAULT_TIMEOUT}" \
       -r requirements-runtime.txt -r requirements-build.txt

FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH \
    ASR_DATA_DIR=/data \
    ASR_MODELS_DIR=/data/models \
    ASR_FORWARDED_ALLOW_IPS=127.0.0.1,172.29.0.0/16

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=python-builder /opt/venv /opt/venv
WORKDIR /app
COPY app.py ./
COPY asr_service ./asr_service
RUN useradd --create-home --uid 10001 asr \
    && mkdir -p /data/models \
    && chown -R asr:asr /app /data
USER asr
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/live || exit 1
CMD ["sh","-c","exec uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips \"$ASR_FORWARDED_ALLOW_IPS\""]
