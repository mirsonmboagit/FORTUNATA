"""Compatibilidade para imports antigos, agora sem HTTP nem API.

O antigo conector remoto foi substituido por licencas locais assinadas. Novos
modulos devem importar :class:`OfflineLicenseClient` diretamente.
"""

from licensing.offline import LicenseResult, OfflineLicenseClient


LicenseClient = OfflineLicenseClient

__all__ = ["LicenseClient", "OfflineLicenseClient", "LicenseResult"]
