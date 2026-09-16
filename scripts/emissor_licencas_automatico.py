"""Processo local que emite licencas por e-mail sem servidor ou API."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from licensing.automatic_email import AutomaticEmailError, run_superadmin_emitter
from licensing.superadmin import LocalSuperadmin, SuperadminError


def main() -> int:
    service = LocalSuperadmin()
    try:
        status = service.automatic_email_status()
        if not status.get("configured"):
            print("O emissor automatico ainda nao foi configurado no superadmin local.")
            print("Abra scripts\\abrir_superadmin_local.cmd e escolha a opcao de configuracao automatica.")
            return 1
        print(
            "Emissor automatico local ativo. "
            f"A verificar o Gmail a cada {status['poll_seconds']} segundos. Prima Ctrl+C para parar."
        )
        run_superadmin_emitter(service)
    except (SuperadminError, AutomaticEmailError) as error:
        print(f"O emissor automatico parou: {error}")
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nEmissor automatico interrompido.")
        raise SystemExit(0)
