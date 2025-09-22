FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y \
    ffmpeg \
    opus-tools \
    libopus-dev \
    libffi-dev \
    libnacl-dev \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r oscillate && useradd -r -g oscillate oscillate

WORKDIR /app

COPY pyproject.toml setup.cfg ./
RUN pip install --upgrade pip setuptools wheel
RUN pip install -e .

COPY src/ src/
COPY tests/ tests/
COPY README.md LICENSE ./

RUN mkdir -p /app/data /app/logs && \
    chown -R oscillate:oscillate /app

USER oscillate

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import oscillate; print('OK')" || exit 1

EXPOSE 8000

CMD ["python", "-c", "import oscillate; print('Oscillate container ready')"]

LABEL maintainer="rae1st <dev@rae1st.com>"
LABEL description="Oscillate Discord Audio Streaming Package"
LABEL version="1.0.0"
LABEL org.opencontainers.image.source="https://github.com/rae1st/oscillate"
