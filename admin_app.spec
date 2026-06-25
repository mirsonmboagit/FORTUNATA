# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


ROOT = Path(SPECPATH)


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


def _local_modules(*folders):
    modules = []
    for folder in folders:
        base = ROOT / folder
        if not base.exists():
            continue
        for source in base.rglob("*.py"):
            if "__pycache__" in source.parts:
                continue
            modules.append(".".join(source.relative_to(ROOT).with_suffix("").parts))
    return modules


datas = []
for tree in ("assets", "locales"):
    _add_tree(datas, tree)

for cache_file in (ROOT / "data" / "cache").glob("*") if (ROOT / "data" / "cache").exists() else []:
    if cache_file.is_file():
        datas.append((str(cache_file), "data/cache"))

for config_file in (
    "config/app.json",
    "config/api.json",
    "config/app_settings.json",
    "config/service.json",
    "config/.env.example",
):
    _add_file(datas, config_file)

for folder in ("admin", "user", "utils", "manager"):
    for kv_file in (ROOT / folder).glob("*.kv") if (ROOT / folder).exists() else []:
        datas.append((str(kv_file), folder))

datas += collect_data_files("kivymd", includes=["*.kv", "fonts/*", "images/*"])

hiddenimports = [
    "bcrypt",
    "cv2",
    "fitz",
    "flask",
    "kivy_deps.angle",
    "kivy_deps.glew",
    "kivy_deps.sdl2",
    "kivy_garden.matplotlib.backend_kivyagg",
    "matplotlib.backends.backend_agg",
    "numpy",
    "numpy._core",
    "numpy._core._multiarray_umath",
    "numpy._core.multiarray",
    "numpy.core",
    "numpy.core.multiarray",
    "numpy.core.umath",
    "PIL.Image",
    "pyzbar",
    "pyzbar.pyzbar",
    "pyzbar.wrapper",
    "reportlab.graphics.barcode.code128",
    "reportlab.graphics.barcode.qr",
    "requests",
]

for package in ("kivymd", "kivy_garden"):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass

hiddenimports += _local_modules(
    "admin",
    "user",
    "utils",
    "manager",
    "ui",
    "AI",
    "api",
    "database",
    "pdfs",
    "server",
    "waitress",
)

hiddenimports = sorted(set(hiddenimports))

api_hiddenimports = sorted(set([
    "bcrypt",
    "click",
    "database.automation",
    "database.database",
    "flask",
    "itsdangerous",
    "jinja2",
    "server.app",
    "server.run_api",
    "utils.app_config",
    "utils.env_loader",
    "utils.logging_setup",
    "utils.paths",
    "utils.perf_utils",
    "utils.security_questions",
    "utils.vat",
    "waitress",
    "werkzeug",
]))


a = Analysis(
    ["admin_app.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "scripts" / "pyinstaller_kivy_runtime_hook.py")],
    excludes=[],
    noarchive=False,
    optimize=0,
)
api_a = Analysis(
    ["api_server_app.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=api_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
api_pyz = PYZ(api_a.pure)

app_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SIGEMPEAdmin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon" / "admin.ico"),
)

api_exe = EXE(
    api_pyz,
    api_a.scripts,
    [],
    exclude_binaries=True,
    name="SIGEMPEAPI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "icon" / "admin.ico"),
)

coll = COLLECT(
    app_exe,
    api_exe,
    a.binaries,
    api_a.binaries,
    a.datas,
    api_a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SIGEMPEAdmin",
    contents_directory=".",
)
