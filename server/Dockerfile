FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /repo
COPY psepipe_v3_seam/ psepipe_v3_seam/
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY server/ server/
ENV PYTHONPATH=/repo/server:/repo/psepipe_v3_seam
WORKDIR /repo/server
