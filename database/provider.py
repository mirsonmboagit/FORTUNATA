"""Fornecedor da base de dados do aplicativo desktop.

O administrador e o gerente trabalham sobre a mesma base SQLite local. A
aplicacao desktop nao cria nem consulta uma API intermediaria: a separacao de
permissoes e feita pelo perfil autenticado na unica sessao da aplicacao.
"""

from utils.config.app_config import get_database_path


def get_db():
    """Abre a base SQLite partilhada pelos dois paineis desktop."""
    from database.database import Database

    return Database(db_path=str(get_database_path()))


def uses_remote_backend(_db):
    """Compatibilidade para telas antigas: o desktop opera sempre localmente."""
    return False
