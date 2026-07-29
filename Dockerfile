FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --target=/deps -r requirements.txt

FROM python:3.12-slim

WORKDIR /app

# Runtime only needs the installed packages, not pip itself — pip's own
# vendored copies of setuptools/msgpack (pip/_vendor/vendor.txt) otherwise
# show up as unfixable CVEs in image scans despite never being used by
# sync.py.
RUN rm -rf /usr/local/lib/python3.12/site-packages/pip* \
           /usr/local/lib/python3.12/ensurepip

COPY --from=builder /deps /usr/local/lib/python3.12/site-packages
COPY . .

CMD ["python", "sync.py"]
