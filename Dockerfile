# Local Linear: web app (8000) and MCP server over HTTP (8765) in one container.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies first so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY docker/start.sh /usr/local/bin/start.sh
RUN uv sync --frozen --no-dev \
    && sed -i 's/\r$//' /usr/local/bin/start.sh \
    && chmod +x /usr/local/bin/start.sh

# Run as a non-root user; the SQLite database lives in the /data volume.
RUN useradd --system --uid 10001 app && mkdir /data && chown app /data
USER app
ENV LOCAL_LINEAR_DB=sqlite:////data/local_linear.db
VOLUME /data

EXPOSE 8000 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/teams', timeout=3)"

CMD ["start.sh"]
