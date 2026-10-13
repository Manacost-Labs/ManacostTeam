FROM python:3.12-slim
WORKDIR /app
COPY server ./server
COPY shared ./shared
COPY games ./games
COPY profiles ./profiles
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8800
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8800/health', timeout=3)"
CMD ["python", "-m", "server.api"]
