# Contributing

Arachne is a lightweight orchestration portal for CI/CD workflows, infrastructure automation, logs, and artifacts.

## Ground rules

- Keep the core generic. Product-specific or company-specific behavior belongs in local scenario files, not in framework code.
- Do not commit secrets, access tokens, private keys, internal hostnames, production logs, customer data, or local certificates.
- Prefer examples based on `*.example.internal`, `example-*`, and local demo services.
- Keep drivers behind the spider interfaces. The core should not import concrete backends directly.
- Keep scenario files readable and operator-friendly.

## Development loop

```bash
cp .env.example .env
make up
make logs
```

For a rebuild after changes:

```bash
make update
```

## Pull requests

A good pull request should include:

- what changed;
- why it changed;
- operator impact;
- compatibility notes;
- validation steps.

## License

By contributing to Arachne, you agree that your contribution is licensed under the Apache License, Version 2.0.
