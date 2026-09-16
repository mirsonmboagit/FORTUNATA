"""Compatibilidade para instalacoes anteriores ao licenciamento offline."""

from licensing.offline_issuer_key import OFFLINE_LICENSE_PUBLIC_KEY


# O emissor atual e local e offline; nao existe URL confiavel a configurar.
TRUSTED_OFFLINE_LICENSE_PUBLIC_KEY = OFFLINE_LICENSE_PUBLIC_KEY
