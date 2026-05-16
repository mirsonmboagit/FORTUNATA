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
    "fitz",
    "kivy_deps.angle",
    "kivy_deps.glew",
    "kivy_deps.sdl2",
    "kivy_garden.matplotlib.backend_kivyagg",
    "matplotlib.backends.backend_agg",
    "PIL.Image",
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
)

hiddenimports = sorted(set(hiddenimports))


a = Analysis(
    ["admin_app.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MerceariaAdmin",
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
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MerceariaAdmin",
    contents_directory=".",
)
