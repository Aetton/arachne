# Deployment

Start from the example environment and Compose files, then supply deployment-specific
secrets and endpoints outside git.

Before users access the portal:

- configure TLS and keep certificate verification enabled;
- use a long random session signing value;
- change the initial administrator password;
- use dedicated service accounts for execution backends;
- verify that workers can reach `ARACHNE_URL`;
- back up PostgreSQL.
