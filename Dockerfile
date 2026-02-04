FROM python:3.11-slim

WORKDIR /app

# Устанавливаем сетевые утилиты для диагностики
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        iputils-ping \
        iproute2 \
        netcat-openbsd \
        dnsutils \
        traceroute \
        curl \
        telnet \
        && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "app.bot"]