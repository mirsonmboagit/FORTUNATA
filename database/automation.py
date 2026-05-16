from __future__ import annotations

import logging
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta

from utils.paths import TEMP_DIR


LOGGER = logging.getLogger(__name__)


class DatabaseAutomationMixin:
    def _get_automation_state_dt(self, state_key):
        try:
            self.cursor.execute(
                "SELECT state_value FROM automation_state WHERE state_key = ?",
                (state_key,),
            )
            row = self.cursor.fetchone()
            if not row or not row[0]:
                return None
            return datetime.fromisoformat(str(row[0]))
        except Exception:
            return None

    def _set_automation_state(self, state_key, state_value):
        now = self._now_str()
        self.cursor.execute(
            """
            INSERT INTO automation_state (state_key, state_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET
                state_value = excluded.state_value,
                updated_at = excluded.updated_at
            """,
            (state_key, str(state_value or ""), now),
        )

    def _cleanup_old_backups(self, retention_days=None):
        retention_days = retention_days or self.BACKUP_RETENTION_DAYS
        root = self.backup_root
        if not os.path.isdir(root):
            return 0

        cutoff = datetime.now() - timedelta(days=int(retention_days))
        removed = 0

        for dirpath, _dirnames, filenames in os.walk(root):
            for fname in filenames:
                if not fname.lower().endswith((".db", ".sqlite", ".sqlite3", ".bak")):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                    if mtime < cutoff:
                        os.remove(fpath)
                        removed += 1
                except Exception:
                    continue

        for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
            try:
                if dirpath != root and not os.listdir(dirpath):
                    os.rmdir(dirpath)
            except Exception:
                pass

        return removed

    def _verify_backup_restore(self, backup_path):
        try:
            with sqlite3.connect(backup_path) as conn_backup:
                cur = conn_backup.cursor()
                cur.execute("PRAGMA integrity_check")
                row = cur.fetchone()
                if not row or str(row[0]).lower() != "ok":
                    return False, "integrity_check_failed"
        except Exception as exc:
            return False, f"integrity_open_failed: {exc}"

        tmp_fd = None
        tmp_path = None
        try:
            TEMP_DIR.mkdir(parents=True, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(
                prefix="restore_test_",
                suffix=".db",
                dir=str(TEMP_DIR),
            )
            os.close(tmp_fd)
            tmp_fd = None

            with sqlite3.connect(backup_path) as src, sqlite3.connect(tmp_path) as dst:
                src.backup(dst)
                cur = dst.cursor()
                cur.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'")
                tables_count = int((cur.fetchone() or [0])[0])
                if tables_count <= 0:
                    return False, "restore_validation_failed_no_tables"
                cur.execute("SELECT 1 FROM sqlite_master WHERE name = 'products' LIMIT 1")
                if not cur.fetchone():
                    return False, "restore_validation_failed_products_missing"
            return True, "ok"
        except Exception as exc:
            return False, f"restore_test_failed: {exc}"
        finally:
            try:
                if tmp_fd is not None:
                    os.close(tmp_fd)
            except Exception:
                pass
            try:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    def create_verified_backup(self):
        try:
            now = datetime.now()
            day_folder = os.path.join(self.backup_root, now.strftime("%Y-%m-%d"))
            os.makedirs(day_folder, exist_ok=True)

            db_stem = os.path.splitext(os.path.basename(self.db_path))[0] or "inventory"
            backup_name = f"{db_stem}_backup_{now.strftime('%H-%M-%S')}.sqlite3"
            backup_path = os.path.join(day_folder, backup_name)

            self.conn.commit()
            with sqlite3.connect(backup_path) as backup_conn:
                self.conn.backup(backup_conn)

            ok, reason = self._verify_backup_restore(backup_path)
            if not ok:
                try:
                    os.remove(backup_path)
                except Exception:
                    pass
                return {"ok": False, "path": backup_path, "reason": reason}

            removed = self._cleanup_old_backups(self.BACKUP_RETENTION_DAYS)
            return {"ok": True, "path": backup_path, "removed_old": removed}
        except Exception as exc:
            return {"ok": False, "path": None, "reason": str(exc)}

    def run_stock_reconciliation(self):
        now = self._now_str()
        tolerance = float(self.RECONCILE_DIFF_TOLERANCE)
        issues = []

        try:
            self.cursor.execute("SELECT id, existing_stock FROM products")
            products_stock = {int(pid): float(stk or 0.0) for pid, stk in self.cursor.fetchall()}

            self.cursor.execute(
                """
                SELECT product_id, id, direction, qty, stock_before, stock_after
                FROM stock_movements
                WHERE applied = 1
                ORDER BY product_id ASC, created_at ASC, id ASC
                """
            )
            chain_rows = self.cursor.fetchall()

            previous_after = {}
            latest_after = {}

            for product_id, movement_id, direction, qty, stock_before, stock_after in chain_rows:
                product_id = int(product_id)
                qty = float(qty or 0.0)
                before = float(stock_before or 0.0)
                after = float(stock_after or 0.0)
                prev = previous_after.get(product_id)

                if prev is not None and abs(before - prev) > tolerance:
                    issues.append(
                        (
                            now,
                            product_id,
                            "CHAIN_BREAK",
                            movement_id,
                            before,
                            after,
                            prev,
                            products_stock.get(product_id),
                            before - prev,
                            f"before={before:.4f} previous_after={prev:.4f}",
                        )
                    )

                if direction == "IN":
                    expected_after = before + qty
                elif direction == "OUT":
                    expected_after = before - qty
                else:
                    expected_after = before

                if direction not in ("IN", "OUT") or abs(after - expected_after) > tolerance:
                    issues.append(
                        (
                            now,
                            product_id,
                            "MOVEMENT_MISMATCH",
                            movement_id,
                            before,
                            after,
                            expected_after,
                            products_stock.get(product_id),
                            after - expected_after,
                            f"direction={direction} qty={qty:.4f}",
                        )
                    )

                previous_after[product_id] = after
                latest_after[product_id] = after

            for product_id, current_stock in products_stock.items():
                if product_id not in latest_after:
                    continue
                expected_current = float(latest_after[product_id])
                diff = current_stock - expected_current
                if abs(diff) > tolerance:
                    issues.append(
                        (
                            now,
                            product_id,
                            "FINAL_STOCK_MISMATCH",
                            None,
                            None,
                            expected_current,
                            expected_current,
                            current_stock,
                            diff,
                            (
                                "products.existing_stock="
                                f"{current_stock:.4f} latest_after={expected_current:.4f}"
                            ),
                        )
                    )

            self.cursor.execute(
                """
                DELETE FROM stock_reconciliation_issues
                WHERE check_run_at < DATETIME('now', '-90 day')
                """
            )

            if issues:
                self.cursor.executemany(
                    """
                    INSERT INTO stock_reconciliation_issues (
                        check_run_at, product_id, issue_type, movement_id,
                        stock_before, stock_after, expected_stock_after,
                        current_stock, diff_qty, details
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    issues,
                )

            self.conn.commit()
            return {
                "ok": True,
                "checked_products": len(products_stock),
                "issues_found": len(issues),
            }
        except Exception as exc:
            self.conn.rollback()
            return {
                "ok": False,
                "checked_products": 0,
                "issues_found": 0,
                "reason": str(exc),
            }

    def run_automation_tasks(self, force=False):
        now = datetime.now()
        summary = {
            "backup": {"executed": False, "ok": True, "reason": ""},
            "reconcile": {"executed": False, "ok": True, "issues": 0, "reason": ""},
        }
        try:
            should_backup = bool(force)
            if not should_backup:
                last_backup = self._get_automation_state_dt("auto_backup_last_run")
                should_backup = (last_backup is None) or (
                    now - last_backup >= timedelta(hours=self.BACKUP_INTERVAL_HOURS)
                )
            if should_backup:
                backup_result = self.create_verified_backup()
                summary["backup"]["executed"] = True
                summary["backup"]["ok"] = bool(backup_result.get("ok"))
                summary["backup"]["reason"] = str(backup_result.get("reason") or "")
                self._set_automation_state("auto_backup_last_run", now.isoformat())
                self._set_automation_state(
                    "auto_backup_last_status",
                    "ok" if backup_result.get("ok") else (backup_result.get("reason") or "error"),
                )

            should_reconcile = bool(force)
            if not should_reconcile:
                last_reconcile = self._get_automation_state_dt("auto_reconcile_last_run")
                should_reconcile = (last_reconcile is None) or (
                    now - last_reconcile >= timedelta(minutes=self.RECONCILE_INTERVAL_MINUTES)
                )
            if should_reconcile:
                rec_result = self.run_stock_reconciliation()
                summary["reconcile"]["executed"] = True
                summary["reconcile"]["ok"] = bool(rec_result.get("ok"))
                summary["reconcile"]["issues"] = int(rec_result.get("issues_found") or 0)
                summary["reconcile"]["reason"] = str(rec_result.get("reason") or "")
                self._set_automation_state("auto_reconcile_last_run", now.isoformat())
                self._set_automation_state(
                    "auto_reconcile_last_status",
                    f"ok:{summary['reconcile']['issues']}"
                    if rec_result.get("ok")
                    else (rec_result.get("reason") or "error"),
                )

            self.conn.commit()
        except Exception as exc:
            self.conn.rollback()
            LOGGER.warning("Erro ao executar automacoes: %s", exc)
        return summary
