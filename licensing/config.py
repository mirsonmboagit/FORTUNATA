"""Configuracao nao secreta do licenciamento offline.

A chave publica e incorporada no pacote pelo terminal do superadmin. Nao ha
URL, servidor de licencas ou configuracao de API neste modo.
"""

from __future__ import annotations

from dataclasses import dataclass

from licensing.offline_issuer_key import OFFLINE_LICENSE_PUBLIC_KEY


@dataclass(frozen=True)
class LicenseSettings:
    issuer_public_key: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.issuer_public_key)


def get_license_settings(**_ignored) -> LicenseSettings:
    """Mantem compatibilidade sem aceitar URL ou chave editavel do cliente."""
    return LicenseSettings(issuer_public_key=OFFLINE_LICENSE_PUBLIC_KEY)
