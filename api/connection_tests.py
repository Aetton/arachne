"""Read-only connection probes for the admin forms.

Probes use form values without persisting them. Do not include response bodies,
credentials or URLs with query parameters in results or logs.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

import httpx

from secrets_store import resolve_credential, VaultSecretProvider, DatabaseSecretProvider
from service_credentials import SERVICE_SPECS

_logger = logging.getLogger(__name__)


def _endpoint(value: str) -> str:
    url = urlsplit(str(value or "").strip())
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment):
        raise ValueError("An HTTPS URL without credentials, query or fragment is required")
    return url.geturl().rstrip("/")


def _probe(url: str, *, headers=None, auth=None, verify=True) -> dict:
    try:
        with httpx.Client(timeout=8, verify=verify, follow_redirects=False, trust_env=False) as client:
            response = client.get(url, headers=headers, auth=auth)
        status = response.status_code
        if status in (401, 403):
            return {"ok": False, "stage": "auth", "detail": f"HTTP {status}: authentication/permissions failed"}
        if 300 <= status < 400:
            return {"ok": False, "stage": "http", "detail": f"Unexpected redirect (HTTP {status})"}
        if status >= 400:
            return {"ok": False, "stage": "http", "detail": f"Service returned HTTP {status}"}
        return {"ok": True, "stage": "api", "detail": f"API responded with HTTP {status}"}
    except httpx.ConnectTimeout:
        return {"ok": False, "stage": "tcp", "detail": "Connection timeout"}
    except httpx.ConnectError as exc:
        return {"ok": False, "stage": "network", "detail": f"Connect error ({type(exc.__cause__).__name__ if exc.__cause__ else type(exc).__name__}); check DNS, TCP and TLS"}
    except httpx.TimeoutException:
        return {"ok": False, "stage": "timeout", "detail": "API request timed out"}
    except httpx.HTTPError as exc:
        _logger.exception("Connection probe failed")
        return {"ok": False, "stage": "http", "detail": f"HTTP client error: {type(exc).__name__}"}


def hypervisor(backend: str, endpoint: str, credential_slug: str, insecure: bool) -> dict:
    url = _endpoint(endpoint)
    secret = resolve_credential(credential_slug)
    if backend == "proxmox":
        if secret.kind != "token" or not secret.values.get("token"):
            raise ValueError("Proxmox requires a token credential")
        base = url.removesuffix("/api2/json")
        return _probe(base + "/api2/json/cluster/resources?type=vm",
                      headers={"Authorization": "PVEAPIToken=" + str(secret.values["token"])},
                      verify=not insecure)
    if backend == "ovirt":
        if secret.kind != "basic" or not secret.username or not secret.values.get("password"):
            raise ValueError("oVirt requires a username and password")
        return _probe(url.rstrip("/") + "/templates",
                      headers={"Accept": "application/json"},
                      auth=(secret.username, str(secret.values["password"])),
                      verify=not insecure)
    raise ValueError("Unsupported hypervisor backend")


def service(service: str, credential_slug: str) -> dict:
    if service not in SERVICE_SPECS:
        raise ValueError("Unsupported service")
    secret = resolve_credential(credential_slug)
    if secret.kind not in SERVICE_SPECS[service]["kinds"]:
        raise ValueError("Credential type does not match service")
    if service == "forgejo":
        url = _endpoint(os.getenv("FORGEJO_URL", ""))
        return _probe(url + "/api/v1/user",
                      headers={"Authorization": "token " + str(secret.values.get("token", ""))},
                      verify=os.getenv("FORGEJO_VERIFY_TLS", "true").lower() != "false")
    if service == "gitlab":
        url = _endpoint(os.getenv("GITLAB_URL", ""))
        return _probe(url + "/api/v4/user",
                      headers={"PRIVATE-TOKEN": str(secret.values.get("token", ""))},
                      verify=os.getenv("GITLAB_VERIFY_TLS", "true").lower() != "false")
    if service == "proxmox":
        url = _endpoint(os.getenv("PROXMOX_VE_ENDPOINT", "")).removesuffix("/api2/json")
        return _probe(url + "/api2/json/version",
                      headers={"Authorization": "PVEAPIToken=" + str(secret.values.get("token", ""))},
                      verify=os.getenv("PROXMOX_VE_INSECURE", "false").lower() != "true")
    url = _endpoint(os.getenv("NEXUS_URL", ""))
    return _probe(url + "/service/rest/v1/status",
                  auth=(secret.username, str(secret.values.get("password", ""))))


def provider(kind: str, config: dict) -> dict:
    if kind == "database":
        result = DatabaseSecretProvider().test()
        return {"ok": bool(result.get("ok", True)), "stage": "storage", "detail": str(result.get("detail", "Encrypted database is healthy"))}
    if kind != "vault":
        raise ValueError("Unsupported provider kind")
    config = dict(config)
    config["address"] = _endpoint(config.get("address", ""))
    vault = VaultSecretProvider(config)
    result = vault.test()
    return {"ok": bool(result.get("ok")), "stage": "api", "detail": str(result.get("detail", ""))}
