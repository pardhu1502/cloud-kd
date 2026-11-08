# build from the repo root:  docker build -f service/Dockerfile -t kd-parser:latest .
# The image holds no model weights; they are downloaded from object storage at start-up.
FROM python:3.13.1-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HOME=/tmp

WORKDIR /app
COPY service/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

COPY kd/ kd/
COPY data/schema.json data/schema.json
COPY service/app.py service/app.py

USER 1000
EXPOSE 8000
CMD ["uvicorn", "service.app:app", "--host", "0.0.0.0", "--port", "8000"]
