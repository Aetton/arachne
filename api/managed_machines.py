"""Managed machine registry and lifecycle reaper.

Arachne owns machine lifecycle in PostgreSQL. Provision spiders only return VM
artifacts; this module persists their user-facing identity and backend metadata,
computes absolute expiry timestamps, and destroys expired machines through the
same spider contract used by ordinary scenarios.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import timezone

from database import ManagedMachine, SessionLocal, utcnow
from core.lifetime import parse_lifetime
from core.registry import get_spider
from core.types import Artifact, RunStatus, StepSpec
from core import wire_codec
from core.thread_client import run_step

_ACTIVE_STATES = {"running", "ready", "destroying"}


def _as_aware(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def register_artifact(run_id: str, user_id: int | None, artifact: Artifact) -> None:
    """Persist VM lifecycle state from one structured artifact."""
    if artifact.type != "vm":
        return

    md = dict(artifact.metadata or {})
    backend = str(md.get("backend") or "unknown")
    state = str(md.get("state") or "running")
    vm_id = str(md.get("vm_id") or artifact.location or "") or None
    name = artifact.name

    db = SessionLocal()
    try:
        machine = None
        if vm_id:
            machine = db.query(ManagedMachine).filter(
                ManagedMachine.backend == backend,
                ManagedMachine.vm_id == vm_id,
            ).first()
        if machine is None:
            machine = db.query(ManagedMachine).filter(
                ManagedMachine.backend == backend,
                ManagedMachine.name == name,
                ManagedMachine.state.in_(_ACTIVE_STATES),
            ).order_by(ManagedMachine.id.desc()).first()

        if state == "destroyed":
            if machine:
                machine.state = "destroyed"
                machine.destroyed_at = utcnow()
                machine.expires_at = None
                machine.backend_metadata = md
                db.commit()
            return

        lifetime = md.get("lifetime")
        expires_at = None
        delta = parse_lifetime(lifetime)
        if delta is not None:
            expires_at = utcnow() + delta

        if machine is None:
            machine = ManagedMachine(
                run_id=run_id,
                user_id=user_id,
                name=name,
                vm_id=vm_id,
                ip=str(md.get("ip") or ""),
                os=str(md.get("os") or ""),
                backend=backend,
                state=state,
                credentials_ref=md.get("credentials_ref"),
                backend_metadata=md,
                expires_at=expires_at,
            )
            db.add(machine)
        else:
            machine.run_id = run_id
            machine.user_id = user_id
            machine.ip = str(md.get("ip") or machine.ip or "")
            machine.os = str(md.get("os") or machine.os or "")
            machine.state = state
            machine.credentials_ref = md.get("credentials_ref") or machine.credentials_ref
            machine.backend_metadata = md
            if lifetime not in (None, ""):
                machine.expires_at = expires_at

        db.commit()
    finally:
        db.close()


def list_expired_ids() -> list[int]:
    now = utcnow()
    db = SessionLocal()
    try:
        rows = db.query(ManagedMachine).filter(
            ManagedMachine.state == "running",
            ManagedMachine.expires_at.is_not(None),
            ManagedMachine.expires_at <= now,
        ).all()
        return [row.id for row in rows]
    finally:
        db.close()


def _claim(machine_id: int) -> dict | None:
    """Atomically-ish claim one expired machine for this process.

    The state transition is committed before backend work so overlapping scheduler
    ticks do not launch duplicate destroy calls in one shared database.
    """
    db = SessionLocal()
    try:
        machine = db.get(ManagedMachine, machine_id)
        if not machine or machine.state != "running":
            return None
        expires_at = _as_aware(machine.expires_at)
        if expires_at is None or expires_at > utcnow():
            return None
        machine.state = "destroying"
        db.commit()
        return {
            "id": machine.id,
            "name": machine.name,
            "os": machine.os,
            "backend": machine.backend,
        }
    finally:
        db.close()


def _mark_destroyed(machine_id: int) -> None:
    db = SessionLocal()
    try:
        machine = db.get(ManagedMachine, machine_id)
        if machine:
            machine.state = "destroyed"
            machine.destroyed_at = utcnow()
            machine.expires_at = None
            db.commit()
    finally:
        db.close()


def _mark_reap_failed(machine_id: int, message: str) -> None:
    db = SessionLocal()
    try:
        machine = db.get(ManagedMachine, machine_id)
        if machine:
            machine.state = "reap_failed"
            md = dict(machine.backend_metadata or {})
            md["reap_error"] = message
            md["reap_failed_at"] = utcnow().isoformat()
            machine.backend_metadata = md
            db.commit()
    finally:
        db.close()


async def destroy_expired_machine(machine_id: int) -> None:
    claimed = await asyncio.to_thread(_claim, machine_id)
    if not claimed:
        return

    if claimed["backend"] != "tofu-proxmox":
        await asyncio.to_thread(
            _mark_reap_failed,
            machine_id,
            f"No lifecycle destroy adapter for backend {claimed['backend']}",
        )
        return

    try:
        spider = get_spider("tofu-proxmox")
        step = StepSpec(
            id=f"ttl-{machine_id}",
            spider="tofu-proxmox",
            action="destroy",
            kind=spider.KIND,
            with_={"name": claimed["name"], "os": claimed["os"]},
        )
        result = await run_step(
            f"ttl:{machine_id}:{uuid.uuid4()}",
            step.kind,
            step.spider,
            wire_codec.step_to_dict(step),
            lambda *_args: None,
            context={"lifecycle": "ttl"},
        )
        status = result.get("status")
        if status == RunStatus.SUCCESS:
            await asyncio.to_thread(_mark_destroyed, machine_id)
            return
        await asyncio.to_thread(
            _mark_reap_failed,
            machine_id,
            f"Destroy returned {getattr(status, 'value', status)}",
        )
    except Exception as exc:  # noqa: BLE001
        await asyncio.to_thread(_mark_reap_failed, machine_id, str(exc))


async def reap_expired() -> None:
    for machine_id in await asyncio.to_thread(list_expired_ids):
        await destroy_expired_machine(machine_id)


def start_reaper() -> None:
    """Run TTL cleanup every minute using Arachne's existing scheduler."""
    from plugins.triggers.schedule import get_scheduler

    scheduler = get_scheduler()
    scheduler.add_job(
        reap_expired,
        trigger="interval",
        minutes=1,
        id="managed-machines:ttl-reaper",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
