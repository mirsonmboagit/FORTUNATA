"""Primitiva DPAPI usada pelos cofres locais de licenca e superadmin."""

from __future__ import annotations

import os


class CredentialStorageError(RuntimeError):
    """Dados locais nao podem ser protegidos ou abertos com seguranca."""


class WindowsDPAPIProtector:
    """Protege bytes para o utilizador Windows atual, sem chave no codigo."""

    description = "SIGE MPE offline licensing"

    @staticmethod
    def _module():
        if os.name != "nt":
            raise CredentialStorageError("A protecao de licencas requer Windows DPAPI.")
        try:
            import win32crypt

            return win32crypt
        except Exception as exc:
            raise CredentialStorageError("Windows DPAPI nao esta disponivel nesta instalacao.") from exc

    def protect(self, value: bytes) -> bytes:
        try:
            # CryptProtectData devolve diretamente o blob protegido. Ja
            # CryptUnprotectData devolve uma tupla com a descricao e os bytes.
            return self._module().CryptProtectData(value, self.description, None, None, None, 0)
        except CredentialStorageError:
            raise
        except Exception as exc:
            raise CredentialStorageError("Nao foi possivel proteger a licenca local.") from exc

    def unprotect(self, value: bytes) -> bytes:
        try:
            return self._module().CryptUnprotectData(value, None, None, None, 0)[1]
        except CredentialStorageError:
            raise
        except Exception as exc:
            raise CredentialStorageError("A licenca nao pertence a este utilizador ou computador.") from exc
