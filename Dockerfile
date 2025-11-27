FROM python:3.12-slim

WORKDIR /app

# ”становим зависимости системы (на вс€кий случай дл€ tzdata)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "diary_bot_v2.py"]