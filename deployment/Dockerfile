FROM python:3.11.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

COPY requirements-service-lock.txt ./

RUN python -m pip install --no-cache-dir -r requirements-service-lock.txt \
    && python -m pip check \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin aiops \
    && mkdir -p /app/runtime /app/release /app/kb /app/data \
    && chown -R 10001:10001 /app/runtime /home/aiops

ENV PYTHONPATH=/app/src

COPY src ./src
COPY configs ./configs
COPY deployment/healthcheck.py ./deployment/healthcheck.py

USER 10001:10001

EXPOSE 8000 8501
CMD ["python", "-m", "aiops_diag.service", "serve", "--config", "configs/service.yaml"]
