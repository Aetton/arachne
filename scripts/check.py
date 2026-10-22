"""Run checks with the active Python environment; isolate legacy test globals."""

import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
env = dict(os.environ)
env["PYTHONPATH"] = str(root / "api")
env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
commands = [
    [sys.executable, "-m", "ruff", "check", "api", "--select", "F821,F822,F823,E9"]
]
commands += [
    [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", path.name, "-q"]
    for path in sorted((root / "tests").glob("test_*.py"))
]
commands += [
    ["node", "--check", str(path)]
    for path in sorted((root / "frontend/static/js").glob("*.js"))
]
commands += [["node", "--test", *map(str, sorted((root / "tests").glob("*.cjs")))]]
failed = []
for command in commands:
    print("+ " + " ".join(command), flush=True)
    if subprocess.run(command, cwd=root, env=env).returncode:
        failed.append(command)
if failed:
    print(f"{len(failed)} check(s) failed", file=sys.stderr)
    sys.exit(1)
print("All checks passed")
