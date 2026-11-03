"""Read-only connection probes for the admin forms.

Probes use form values without persisting them. Do not include response bodies,
credentials or URLs with query parameters in results or logs.
"""
from __future__ import annotations

import logging
import ssl
import socket
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from secrets_store import resolve_credential, VaultSecretProvider, DatabaseSecretProvider
from service_credentials import SERVICE_SPECS
from infrastructure_connections import get_ca_pem, tls_verify, _validate_ca_pem

_logger = logging.getLogger(__name__)


def _endpoint(value: str) -> str:
    url = urlsplit(str(value or "").strip())
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment):
        raise ValueError("An HTTPS URL without credentials, query or fragment is required")
    return url.geturl().rstrip("/")


def _probe(url: str, *, headers=None, auth=None, verify=True) -> dict:
    try:
        with httpx.Client(timeout=15, verify=verify, follow_redirects=False) as client:
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
        _logger.exception("Connection probe transport failed")
        cause = exc
        seen = set()
        chain = []
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            chain.append(cause)
            cause = cause.__cause__ or cause.__context__
        description = " ".join(str(item).lower() for item in chain)
        if any(isinstance(item, socket.gaierror) for item in chain) or "name resolution" in description or "getaddrinfo" in description:
            return {"ok": False, "stage": "dns", "detail": "DNS resolution failed"}
        if any(isinstance(item, ssl.SSLError) for item in chain) or any(
            term in description for term in ("certificate verify failed", "ssl:", "tlsv1", "self-signed certificate")
        ):
            return {"ok": False, "stage": "tls", "detail": "TLS verification/handshake failed; check internal CA"}
        if any(isinstance(item, ConnectionRefusedError) for item in chain) or "connection refused" in description:
            return {"ok": False, "stage": "tcp", "detail": "Connection refused"}
        # Do not echo the raw exception text: it can contain an authenticated URL.
        return {"ok": False, "stage": "network", "detail": f"Connection failed ({type(chain[-1]).__name__}); see API logs"}
    except httpx.TimeoutException:
        return {"ok": False, "stage": "timeout", "detail": "API request timed out"}
    except httpx.HTTPError as exc:
        _logger.exception("Connection probe failed")
        return {"ok": False, "stage": "http", "detail": f"HTTP client error: {type(exc).__name__}"}


def hypervisor(backend: str, endpoint: str, credential_slug: str, insecure: bool, *,\n               slug: str = "", ca_action: str = "keep", ca_pem: str = "") -> dict:
    url = _endpoint(endpoint)
    secret = resolve_credential(credential_slug)
    if ca_action == "replace":
        ca = _validate_ca_pem(ca_pem)
    elif ca_action == "clear":
        ca = ""
    elif ca_action == "keep":
        ca = get_ca_pem(slug, backend) if slug else ""
    else:
        raise ValueError("Invalid CA action")
    if backend == "proxmox":
        if secret.kind != "token" or not secret.values.get("token"):
            raise ValueError("Proxmox requires a token credential")
        base = url.removesuffix("/api2/json")
        verify = tls_verify(insecure, ca)
        return _probe(base + "/api2/json/cluster/resources?type=vm",
                      headers={"Authorization": "PVEAPIToken=" + str(secret.values["token"])},
                      verify=verify)
    if backend == "ovirt":
        if secret.kind != "basic" or not secret.username or not secret.values.get("password"):
            raise ValueError("oVirt requires a username and password")
        verify = tls_verify(insecure, ca, ovirt=True)
        return _probe(url.rstrip("/") + "/templates",
                      headers={"Accept": "application/json"},
                      auth=(secret.username, str(secret.values["password"])),
                      verify=verify)
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
    return _probe(url + "/service/rest/v1/repositories",
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
    # Vault health is often intentionally public; a successful health response
    # does not prove the bootstrap credentials. Verify the authenticated token.
    headers = vault._headers()
    return _probe(config["address"] + "/v1/auth/token/lookup-self",
                  headers=headers, verify=config.get("verify_tls", True))
