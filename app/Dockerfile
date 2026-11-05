FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY nusantara_demo /app/nusantara_demo
ENV PYTHONUNBUFFERED=1
