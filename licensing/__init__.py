"""Licenciamento offline assinado do aplicativo desktop.

Nao abre servidor, nao chama API e nao transmite dados da loja. As licencas
sao assinadas no computador do proprietario e entregues por e-mail pelo
emissor local automatico.
"""

from licensing.offline import LicenseResult, OfflineLicenseClient

__all__ = ["OfflineLicenseClient", "LicenseResult"]
