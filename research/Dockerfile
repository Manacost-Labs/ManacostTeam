FROM python:3.12-slim

WORKDIR /app
COPY deep-research ./deep-research

RUN useradd --create-home --uid 10001 research \
    && chown -R research:research /app

USER research
ENV PYTHONUNBUFFERED=1
EXPOSE 8777

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=5 \
    CMD python3 -c "from urllib.request import urlopen; response = urlopen('http://127.0.0.1:8777/health', timeout=3); raise SystemExit(0 if response.status == 200 else 1)"

CMD ["python3", "deep-research/scripts/source_gateway.py"]
