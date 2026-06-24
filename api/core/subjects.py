"""Subject topology of the web. Boring and stable on purpose — one place defines
the naming so nothing drifts into arachne.super.cool.magic.v2.final2.

  arachne.thread.{kind}.{spider}.run      request  → run one step, stream logs
  arachne.thread.{kind}.{spider}.cancel   publish  → cut a running thread
  arachne.thread.{kind}.{spider}.health   request  → {ok: bool}
  arachne.thread.log.{run_id}.{step_id}   publish  ← log lines (vibrations)
  arachne.event.run.completed             publish  ← lifecycle events
  arachne.event.run.started / .failed

kind = build | provision. Including it lets a host subscribe to a whole class
of threads with a wildcard: arachne.thread.build.>
"""


def run(kind: str, spider: str) -> str:
    return f"arachne.thread.{kind}.{spider}.run"


def cancel(kind: str, spider: str) -> str:
    return f"arachne.thread.{kind}.{spider}.cancel"


def health(kind: str, spider: str) -> str:
    return f"arachne.thread.{kind}.{spider}.health"


def log(run_id: str, step_id: str) -> str:
    return f"arachne.thread.log.{run_id}.{step_id}"
