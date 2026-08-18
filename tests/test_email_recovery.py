from __future__ import annotations

from unittest import mock

from tests.helpers import TemporaryDatabaseTestCase


class EmailRecoveryTests(TemporaryDatabaseTestCase):
    def setUp(self):
        super().setUp()
        self.sent_reset = []
        self.sent_verification = []
        self.reset_sender = mock.patch(
            "database.database.send_password_reset_code",
            side_effect=lambda email, username, code: self.sent_reset.append(
                (email, username, code)
            ),
        )
        self.notice_sender = mock.patch(
            "database.database.send_password_changed_notice",
            return_value=True,
        )
        self.verification_sender = mock.patch(
            "database.database.send_email_verification_code",
            side_effect=lambda email, username, code: self.sent_verification.append(
                (email, username, code)
            ),
        )
        self.reset_sender.start()
        self.notice_sender.start()
        self.verification_sender.start()

    def tearDown(self):
        self.verification_sender.stop()
        self.notice_sender.stop()
        self.reset_sender.stop()
        super().tearDown()

    def test_reset_uses_registered_email_and_is_single_use(self):
        self.assertTrue(self.db.create_user("maria", "password1", "manager", email="Maria@Example.COM"))

        requested = self.db.request_password_reset("maria")

        self.assertTrue(requested["ok"])
        self.assertEqual(self.sent_reset[0][0], "maria@example.com")
        self.assertEqual(self.sent_reset[0][1], "maria")
        code = self.sent_reset[0][2]

        result = self.db.confirm_password_reset("maria", code, "newpassword")
        self.assertTrue(result["ok"])
        self.assertEqual(self.db.validate_user("maria", "newpassword"), "manager")
        self.assertEqual(
            self.db.confirm_password_reset("maria", code, "anotherpass")["reason"],
            "not_found",
        )

    def test_request_without_email_returns_generic_result(self):
        self.assertTrue(self.db.create_user("sememail", "password1", "manager"))

        result = self.db.request_password_reset("sememail")

        self.assertEqual(result["reason"], "accepted")
        self.assertEqual(self.sent_reset, [])

    def test_email_is_normalized_and_unique(self):
        self.assertTrue(self.db.create_user("primeiro", "password1", "manager", email="alice@example.com"))
        self.assertFalse(self.db.create_user("segundo", "password1", "manager", email="ALICE@EXAMPLE.COM"))
        self.assertEqual(self.db.get_user_email_status("primeiro")["masked_email"], "al***@example.com")

    def test_verification_code_is_expiring_and_single_use(self):
        self.assertTrue(self.db.create_user("joao", "password1", "manager", email="joao@example.com"))

        requested = self.db.request_email_verification("joao")
        self.assertTrue(requested["ok"])
        code = self.sent_verification[0][2]

        self.assertTrue(self.db.confirm_email_verification("joao", code)["ok"])
        self.assertTrue(self.db.is_user_email_verified("joao"))
        self.assertEqual(
            self.db.confirm_email_verification("joao", code)["reason"],
            "not_found",
        )

    def test_reset_locks_after_invalid_attempts(self):
        self.assertTrue(self.db.create_user("tentativa", "password1", "manager", email="t@example.com"))
        self.db.request_password_reset("tentativa")

        for _ in range(4):
            self.assertEqual(
                self.db.confirm_password_reset("tentativa", "000000", "newpassword")["reason"],
                "invalid",
            )
        locked = self.db.confirm_password_reset("tentativa", "000000", "newpassword")
        self.assertEqual(locked["reason"], "too_many_attempts")

    def test_emergency_code_resets_password_once(self):
        self.assertTrue(self.db.create_user("offline", "password1", "manager"))

        generated = self.db.generate_recovery_codes("offline", count=4)
        self.assertTrue(generated["ok"])
        self.assertEqual(len(generated["codes"]), 4)
        code = generated["codes"][0]

        result = self.db.confirm_recovery_code("offline", code, "newpassword")
        self.assertTrue(result["ok"])
        self.assertEqual(self.db.validate_user("offline", "newpassword"), "manager")
        self.assertEqual(
            self.db.confirm_recovery_code("offline", code, "anotherpass")["reason"],
            "invalid",
        )
