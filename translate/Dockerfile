FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY translate/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY translate/app ./app
COPY shared ./shared
COPY games ./games
COPY profiles ./profiles

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
