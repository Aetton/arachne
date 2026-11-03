# Installation

## Requirements

- Docker with Compose
- [just](https://just.systems/) (command runner)

## Start locally

```bash
git clone https://github.com/Aetton/arachne.git
cd arachne
cp .env.example .env
just up
just logs
```

Open `http://localhost:8080`. Before production use, replace every placeholder
in `.env`, rotate the initial administrator password, and configure TLS.
