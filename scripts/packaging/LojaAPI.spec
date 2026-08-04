# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


ROOT = Path(SPECPATH).parents[1]


def _as_dest(path):
    return str(path).replace("\\", "/")


def _add_file(datas, relative_path):
    source = ROOT / relative_path
    if source.exists():
        datas.append((str(source), _as_dest(Path(relative_path).parent)))


def _add_tree(datas, relative_path):
    source = ROOT / relative_path
    if source.exists():
        datas.append((str(source), _as_dest(Path(relative_path))))


datas = []
for tree in ("assets", "locales"):
    _add_tree(datas, tree)

for config_file in (
    "VERSION",
    "config/app.json",
    "config/api.json",
    "config/app_settings.json",
    "config/service.json",
    "config/.env.example",
):
    _add_file(datas, config_file)

hiddenimports = [
    "bcrypt",
    "click",
    "database.automation",
    "database.database",
    "flask",
    "itsdangerous",
    "jinja2",
    "requests",
    "server.app",
    "server.run_api",
    "utils.config.app_config",
    "utils.config.env_loader",
    "utils.config.logging_setup",
    "utils.config.paths",
    "utils.core.perf_utils",
    "utils.business.security_questions",
    "utils.business.vat",
    "waitress",
    "werkzeug",
]

hiddenimports = sorted(set(hiddenimports))


a = Analysis(
    [str(ROOT / "api_server_app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "cv2",
        "fitz",
        "kivy",
        "kivy_deps",
        "kivy_garden",
        "kivymd",
        "matplotlib",
        "numpy",
        "PIL",
        "pyzbar",
        "reportlab",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LojaAPI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
