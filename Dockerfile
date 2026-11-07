# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:0.13.5 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
COPY --chmod=0644 config/airi.json config/luna.json config/family.json ./config/
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export SSL_CERT_FILE=/run/secrets/proxy_ca; fi; \
    uv sync --frozen --no-dev --no-editable
RUN chmod 0755 /app/config && useradd --uid 10001 --create-home airi && mkdir -p /app/data /app/traces && chown -R airi:airi /app/data /app/traces
USER airi
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["airi"]
CMD ["run"]
