# Architecture overview

Arachne separates the portal and scenario model from execution backends.

```mermaid
flowchart TD
    UI[Portal] --> API[FastAPI core]
    API --> DB[(PostgreSQL)]
    API --> Bus[Event bus]
    Bus --> Driver[Driver plugin]
    Driver --> Backend[Execution backend]
    Backend --> Driver
    Driver --> Bus
    Bus --> API
```

Driver plugins implement dispatch, log streaming, status lookup, and artifact collection.
The in-memory bus is the default for a compact deployment; NATS is available when the
transport must be externalized.
