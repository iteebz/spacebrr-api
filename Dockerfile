FROM node:20-slim

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY space/ ./space/
COPY requirements.txt ./
RUN pip3 install --break-system-packages -r requirements.txt

COPY server.ts provision.py ledger.py close_task.py ./
COPY scripts/ ./scripts/

RUN mkdir -p /root/.space/customers

ENV PORT=8080
EXPOSE 8080

CMD ["npx", "tsx", "server.ts"]
