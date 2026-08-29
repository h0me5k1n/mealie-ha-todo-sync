FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --target=/deps -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

# Pull Debian security fixes that the base image hasn't been rebuilt for yet
# (e.g. the util-linux TOCTOU CVEs). Trivy scans OS packages too, so a stale
# base means fixed-but-not-applied CVEs fail the image scan.
RUN apt-get update && \
    apt-get upgrade -y --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# Runtime only needs the installed packages, not pip itself — pip's own
# vendored copies of setuptools/msgpack (pip/_vendor/vendor.txt) otherwise
# show up as unfixable CVEs in image scans despite never being used by
# sync.py.
RUN rm -rf /usr/local/lib/python3.12/site-packages/pip* \
           /usr/local/lib/python3.12/ensurepip

COPY --from=builder /deps /usr/local/lib/python3.12/site-packages
COPY . .

CMD ["python", "sync.py"]
