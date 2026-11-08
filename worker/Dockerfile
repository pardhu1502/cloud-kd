# build from the repo root:  docker build -f worker/Dockerfile -t kd-worker:latest .
FROM python:3.12-slim

WORKDIR /app
COPY worker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY kd/ kd/
COPY prompts/ prompts/
COPY worker/worker.py worker/clean.py worker/

ENV PYTHONUNBUFFERED=1
USER 1000
CMD ["python", "worker/worker.py"]
