from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _method_source(relative_path: str, method_name: str) -> str:
    source = (ROOT / relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name:
            return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"Metodo ausente: {relative_path}:{method_name}")


def test_client_specs_do_not_bundle_a_second_api_executable():
    for relative_path in (
        "scripts/packaging/manager_app.spec",
        "scripts/packaging/admin_app.spec",
    ):
        source = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "api_server_app.py" not in source
        assert 'name="SIGEMPEAPI"' not in source
        assert "api_exe" not in source


def test_client_connection_wizard_only_configures_clients_safely():
    source = (ROOT / "scripts/setup_connection_wizard.ps1").read_text(encoding="utf-8")
    assert "Start-ApiProcess" not in source
    assert "Register-ApiStartupTask" not in source
    assert "Enable-ApiFirewall" not in source
    assert "A API e preparada apenas no pacote LojaAPI" in source
    assert "Test-ApiConnection -BaseUrl $baseUrl -Key $keyValue" in source
    assert "Configure-Client -Root $root -ServerHost $hostValue" in source
    assert "[string]$Host" not in source


def test_api_package_can_generate_the_client_connection_file():
    script = (ROOT / "scripts/windows/gerar_ligacao_cliente.ps1").read_text(encoding="utf-8")
    build_script = (ROOT / "scripts/build_api_release.ps1").read_text(encoding="utf-8")
    assert "SIGEMPELigacao.json" in script
    assert "api_key = $apiKey" in script
    assert "GERAR_LIGACAO_CLIENTE.bat" in build_script
    assert "gerar_ligacao_cliente.ps1" in build_script


def test_emergency_recovery_is_asynchronous_and_single_submit():
    source = _method_source("user/login.py", "_open_recovery_code_dialog")
    busy_source = _method_source("user/login.py", "_set_forgot_busy")
    assert "if busy or self.operation_in_progress" in source
    assert "self._run_background_task(" in source
    assert "set_busy(True)" in source
    assert "_forgot_recovery_button.disabled" in busy_source


def test_pdf_shortcut_navigates_to_reports_before_opening_viewer():
    source = _method_source("admin/admin_home_screen.py", "show_all_pdfs")
    assert 'self.manager.current = "reports"' in source
    assert "screen.show_pdf_viewer" in source


def test_product_pagination_controls_are_visible_and_bound():
    manager_kv = (ROOT / "manager/sales_screen.kv").read_text(encoding="utf-8")
    admin_kv = (ROOT / "admin/admin_screen.kv").read_text(encoding="utf-8")
    for control_id in ("product_page_label", "product_prev_btn", "product_next_btn"):
        assert f"id: {control_id}" in manager_kv
    assert "root.previous_products_page()" in manager_kv
    assert "root.next_products_page()" in manager_kv
    for control_id in ("admin_page_label", "admin_prev_btn", "admin_next_btn"):
        assert f"id: {control_id}" in admin_kv
    assert "root.previous_product_page()" in admin_kv
    assert "root.next_product_page()" in admin_kv
