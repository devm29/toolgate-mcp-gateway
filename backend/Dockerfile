FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

FROM base AS deps
COPY pyproject.toml ./
COPY src ./src
COPY fixtures ./fixtures
RUN pip install --upgrade pip && pip install .

FROM base AS runtime
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin
COPY src ./src
COPY fixtures ./fixtures
COPY migrations ./migrations
COPY alembic.ini ./
RUN useradd --uid 10001 --create-home toolgate && chown -R toolgate /app
USER toolgate
EXPOSE 8101
CMD ["uvicorn", "toolgate.main:app", "--host", "0.0.0.0", "--port", "8101"]
