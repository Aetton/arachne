# Installation

## Requirements

- Docker with Compose
- GNU Make

## Start locally

```bash
git clone https://github.com/Aetton/arachne.git
cd arachne
cp .env.example .env
make up
make logs
```

Open `http://localhost:8080`. Before production use, replace every placeholder
in `.env`, rotate the initial administrator password, and configure TLS.
