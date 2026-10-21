FROM python:3.14-alpine
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.runtime.lock pyproject.toml ./
COPY backend ./backend
RUN pip install --no-cache-dir -r requirements.runtime.lock && pip install --no-cache-dir --no-deps . && addgroup -g 10001 sentinel && adduser -D -u 10001 -G sentinel sentinel && pip uninstall -y pip setuptools wheel && rm -rf /usr/local/lib/python3.14/ensurepip && mkdir /logs && chown sentinel /logs
COPY rules ./rules
COPY migrations ./migrations
COPY alembic.ini ./
USER 10001
EXPOSE 8000
CMD ["uvicorn", "sentinel.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
