FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m app && mkdir -p /data/jobs && chown -R app /app /data
USER app
ENV JOBS_DIR=/data/jobs PORT=8000 TRUST_PROXY=1
EXPOSE 8000
# ONE worker: the job queue and rate limits are in memory. Threads handle concurrency.
CMD ["sh", "-c", "gunicorn -w 1 --threads 8 --timeout 120 -b 0.0.0.0:${PORT} server:app"]
