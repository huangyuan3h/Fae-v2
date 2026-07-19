# ASR stub for local compose (no GPU). Real Qwen3-ASR lands later.
FROM python:3.12-slim-bookworm

WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.12 uvicorn==0.34.2
COPY deploy/docker/asr-stub/main.py /app/main.py

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
