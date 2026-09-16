from __future__ import annotations

import bcrypt
from pathlib import Path
from uuid import uuid4

from tests.helpers import TemporaryDatabaseTestCase


class ProvisionedAdminDatabaseTests(TemporaryDatabaseTestCase):
    def test_provisioned_admin_is_the_only_admin_and_must_change_password(self):
        password_hash = bcrypt.hashpw(b"SenhaTemporaria!2026", bcrypt.gensalt()).decode("ascii")
        provisioning_id = str(uuid4())

        self.assertTrue(
            self.quiet(
                self.db.create_provisioned_admin,
                "admin.loja",
                password_hash,
                email="admin@example.com",
                provisioning_id=provisioning_id,
            )
        )
        self.assertEqual(self.db.validate_user("admin.loja", "SenhaTemporaria!2026"), "admin")
        self.assertTrue(self.db.is_password_change_required("admin.loja"))

        # Nenhuma rota local pode introduzir um segundo admin.
        self.assertFalse(self.quiet(self.db.create_admin, "outro.admin", "OutraSenha!2026"))
        self.assertFalse(
            self.quiet(self.db.create_user, "outro.admin", "OutraSenha!2026", "admin")
        )
        self.assertTrue(
            self.quiet(
                self.db.create_user,
                "gerente.loja",
                "SenhaGerente!2026",
                "manager",
                data_owner="admin.loja",
            )
        )

        # O recibo do codigo impede reaproveitamento mesmo se a conta for
        # removida fora do fluxo normal por uma manutencao indevida.
        self.db.cursor.execute("DELETE FROM users WHERE username = ?", ("admin.loja",))
        self.db.conn.commit()
        self.assertFalse(
            self.quiet(
                self.db.create_provisioned_admin,
                "admin.loja",
                password_hash,
                provisioning_id=provisioning_id,
            )
        )

    def test_password_change_clears_temporary_state_without_exposing_hash(self):
        password_hash = bcrypt.hashpw(b"SenhaTemporaria!2026", bcrypt.gensalt()).decode("ascii")
        self.assertTrue(
            self.quiet(
                self.db.create_provisioned_admin,
                "admin.loja",
                password_hash,
                provisioning_id=str(uuid4()),
            )
        )

        self.assertTrue(
            self.quiet(
                self.db.update_user_password,
                "admin.loja",
                "SenhaDefinitiva!2026",
                "admin",
            )
        )
        self.assertFalse(self.db.is_password_change_required("admin.loja"))
        self.assertEqual(self.db.validate_user("admin.loja", "SenhaDefinitiva!2026"), "admin")

        status = self.db.get_user_security_status("admin.loja")
        self.assertTrue(status["password_changed_at"])
        self.assertNotIn("password", status)
        self.assertNotIn("hash", status)

    def test_login_temporarily_locks_after_repeated_failures(self):
        self.assertTrue(self.quiet(self.db.create_admin, "admin.loja", "SenhaForte!2026"))

        for _ in range(self.db.LOGIN_MAX_FAILED_ATTEMPTS):
            self.assertIsNone(self.db.validate_user("admin.loja", "senha-errada"))
        self.assertEqual(self.db.get_last_authentication_status(), "locked")
        self.assertIsNone(self.db.validate_user("admin.loja", "SenhaForte!2026"))
        self.assertEqual(self.db.get_last_authentication_status(), "locked")


def test_settings_dialog_can_only_create_managers():
    source = (Path(__file__).resolve().parents[1] / "utils" / "screens" / "settings.py").read_text(
        encoding="utf-8"
    )
    dialog_source = source.split("class AddUserDialog:", 1)[1].split(
        "class SecurityQuestionsDialog:", 1
    )[0]

    assert "self.selected_role = 'manager'" in dialog_source
    assert "db.create_user(username, password, 'manager'" in dialog_source
    assert "self.role_admin_btn" not in dialog_source
    assert "select_role('admin')" not in dialog_source
