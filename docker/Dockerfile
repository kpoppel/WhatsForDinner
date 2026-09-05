FROM node:22-slim AS client-build

WORKDIR /app

COPY package.json package-lock.json /app/
RUN npm ci

COPY app/static /app/app/static
COPY scripts/build-client.mjs /app/scripts/build-client.mjs
RUN npm run build:client

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY --from=client-build /app/app/static/dist /app/app/static/dist

RUN mkdir -p /data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
