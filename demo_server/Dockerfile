# Demo company systems on port 8100. Build context is this folder:
#   docker build -t support-desk-demo-server demo_server
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . demo_server/

RUN useradd --system --uid 10002 demo
USER demo

EXPOSE 8100
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/ping', timeout=4)"

CMD ["uvicorn", "demo_server.main:app", "--host", "0.0.0.0", "--port", "8100"]
