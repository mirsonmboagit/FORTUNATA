import sqlite3
from types import SimpleNamespace

import pytest

from licensing.user_directory import local_user_directory
from licensing.superadmin import SuperadminError
from scripts.superadmin_terminal import _print_table


def test_directory_links_only_imported_accounts_and_never_changes_database(tmp_path):
    path = tmp_path / "users.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE users (id INTEGER, username TEXT, role TEXT, password TEXT, data_owner TEXT)")
        db.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?)", [
            (1, "joe", "admin", b"$2b$test", "joe"),
            (2, "lara", "admin", "$2b$test", "lara"),
            (3, "mirson", "manager", "$2b$test", "joe"),
        ])
        db.execute("CREATE TABLE admin_provisioning_receipts (provisioning_id TEXT, username TEXT)")
        db.execute("INSERT INTO admin_provisioning_receipts VALUES ('p1', 'joe')")
    before = path.read_bytes()
    service = SimpleNamespace(
        list_licenses=lambda: [{"license_id": "l1", "license_reference": "MIRSON-0001"}, {"license_id": "l2"}],
        list_admin_provisionings=lambda: [
            {"provisioning_id": "p1", "username": "joe", "license_id": "l1"},
            {"provisioning_id": "p2", "username": "lara", "license_id": "l2"},
        ],
    )
    result = local_user_directory(service, database_path=path, license_store=SimpleNamespace(load=lambda: {}))
    users = {row["username"]: row for row in result["users"]}
    assert users["joe"]["owner_license"]["license_id"] == "l1"
    assert users["mirson"]["owner_license"]["license_id"] == "l1"
    assert users["lara"]["owner_license"] is None
    assert users["joe"]["stored_password_value"] == "$2b$test"
    assert "irrecuperavel" in users["joe"]["password_storage"]
    assert path.read_bytes() == before


def test_missing_database_does_not_create_file(tmp_path):
    path = tmp_path / "missing.db"
    with pytest.raises(SuperadminError, match="nao encontrada"):
        local_user_directory(None, database_path=path)
    assert not path.exists()


def test_table_wraps_without_truncating(capsys):
    _print_table(["Utilizador"], [["abcdefghijklmnop"]], [8])
    output = capsys.readouterr().out
    assert "abcdefgh" in output and "ijklmnop" in output
