"""Stable bus subject topology.

  arachne.thread.{kind}.{spider}.run
  arachne.thread.{kind}.{spider}.cancel
  arachne.thread.{kind}.{spider}.health
  arachne.thread.log.{run_id}.{step_id}
  arachne.event.run.completed

``kind`` is a transport concern, not the public spider taxonomy. During the
Weave/Brood/Command migration the wire keeps the compatible values ``build`` and
``provision``. Spider ``FAMILY`` carries the domain meaning.
"""


def run(kind: str, spider: str) -> str:
    return f"arachne.thread.{kind}.{spider}.run"


def cancel(kind: str, spider: str) -> str:
    return f"arachne.thread.{kind}.{spider}.cancel"


def health(kind: str, spider: str) -> str:
    return f"arachne.thread.{kind}.{spider}.health"


def log(run_id: str, step_id: str) -> str:
    return f"arachne.thread.log.{run_id}.{step_id}"
