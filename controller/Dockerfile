FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV STOCKFISH_PATH=/usr/games/stockfish
ENV BASE_URL=http://127.0.0.1:8000
ENV VIEWER_BASE_URL=http://127.0.0.1:8000
ENV LIB_DIR=/usr/lib/x86_64-linux-gnu
ENV OUTPUT_DIR=/app/captures_fastapi_physical

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-numpy \
    python3-opencv \
    stockfish \
    libfreenect-dev \
    libfreenect0.5 \
    libusb-1.0-0-dev \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libx11-6 \
    libxcb1 \
    x11-apps \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir -r /app/requirements.txt

COPY . /app
RUN chmod +x /app/scripts/*.sh

EXPOSE 8000 8765

CMD ["/app/scripts/start-api.sh"]
