"""Verificacoes rapidas e deterministicas antes de criar uma release."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REQUIRED = (
    "VERSION",
    "admin_app.py",
    "manager_app.py",
    "api_server_app.py",
    "config/.env.example",
    "scripts/packaging/admin_app.spec",
    "scripts/packaging/manager_app.spec",
    "scripts/packaging/LojaAPI.spec",
)


def fail(message: str) -> None:
    print(f"ERRO: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_required_files() -> None:
    missing = [name for name in REQUIRED if not (ROOT / name).is_file()]
    if missing:
        fail("ficheiros obrigatorios ausentes: " + ", ".join(missing))


def check_version() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not version or any(not part.isdigit() for part in version.split(".")):
        fail("VERSION deve usar numeros separados por pontos, por exemplo 1.0.0")
    from version import __version__

    if version != __version__:
        fail(f"VERSION ({version}) difere de version.py ({__version__})")
    return version


def check_json_configs() -> None:
    for relative in ("config/app.json", "config/api.json", "config/service.json", "config/app_settings.json"):
        try:
            json.loads((ROOT / relative).read_text(encoding="utf-8-sig"))
        except Exception as exc:
            fail(f"JSON invalido em {relative}: {exc}")


def check_tracked_secrets() -> None:
    result = subprocess.run(
        ["git", "ls-files", ".env", "config/.env", "database/*.db*"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    tracked = [line for line in result.stdout.splitlines() if line.strip()]
    if tracked:
        fail("segredos ou bases locais versionados: " + ", ".join(tracked))


def run_tests() -> None:
    completed = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, check=False)
    if completed.returncode:
        fail("a suite automatizada falhou")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    check_required_files()
    version = check_version()
    check_json_configs()
    check_tracked_secrets()
    if not args.skip_tests:
        run_tests()
    print(f"Preflight aprovado para SIGE MPE {version}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
