# Configuration

Copy `.env.example` to `.env` and replace the placeholders for the target environment.
Keep credentials and environment-specific hosts outside committed scenario definitions.

The default deployment uses PostgreSQL and the in-memory bus. A NATS-backed bus can be
enabled through the provided Compose profile and `BUS_BACKEND`.
