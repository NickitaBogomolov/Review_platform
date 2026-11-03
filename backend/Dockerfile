FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FLASK_APP=wsgi.py
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000
# Анализ MR синхронный (модель может отвечать долго) — поэтому большой timeout
# seed-demo в демо-режиме загружает демо-MR и примеры правил линтера; при GITLAB_MOCK=false ничего не делает
CMD ["sh", "-c", "flask db upgrade && flask seed-demo && gunicorn -w 2 --timeout 600 -b 0.0.0.0:5000 wsgi:app"]
