FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md alembic.ini ./
COPY tensordata ./tensordata
COPY migrations ./migrations
RUN pip install --no-cache-dir .
ENV TENSORDATA_DATABASE_URL=sqlite:////data/tensordata.db
ENV TENSORDATA_STORAGE_ROOT=/data/artifacts
VOLUME ["/data"]
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn tensordata.main:app --host 0.0.0.0 --port 8000"]
