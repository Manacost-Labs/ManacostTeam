# Контекст сборки — корень репозитория:
#   docker build -f studio/Dockerfile -t manacost-studio .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/srv/studio:/srv/shared:/srv/editor/src

WORKDIR /srv
COPY studio/requirements.txt studio/requirements.txt
RUN pip install --no-cache-dir -r studio/requirements.txt

# Метаданные игр/профилей для task_context (shared/manacost_context.py ищет ../games).
COPY shared/manacost_context.py shared/manacost_context.py
COPY games/registry.json games/registry.json
COPY profiles/registry.json profiles/registry.json
# Шорткоды карт вызываются в процессе — те же модули, что в навыке card-shortcodes.
COPY editor/src/editorteam/__init__.py editor/src/editorteam/wordpress.py editor/src/editorteam/card_shortcodes.py editor/src/editorteam/
COPY studio/app studio/app
COPY studio/static studio/static

RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin studio
USER 10001

WORKDIR /srv/studio
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"]
CMD ["python", "-m", "uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-server-header"]
