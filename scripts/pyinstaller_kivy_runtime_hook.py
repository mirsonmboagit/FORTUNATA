"""Runtime fixes needed before Kivy imports its Windows dependency packages."""

import os
import site
import sys


def _bundle_base():
    return getattr(sys, "_MEIPASS", None) or sys.prefix or os.getcwd()


def _ensure_site_user_base():
    # Some kivy_deps packages call os.path.join(site.USER_BASE, ...). In a
    # PyInstaller app site.USER_BASE can be None, which raises during import.
    if getattr(site, "USER_BASE", None) is None:
        site.USER_BASE = _bundle_base()


def _add_dll_dir(path):
    if not path or not os.path.isdir(path):
        return
    os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(path)
        except OSError:
            pass


_ensure_site_user_base()

base = _bundle_base()
_add_dll_dir(base)
for dependency in ("angle", "glew", "sdl2"):
    _add_dll_dir(os.path.join(base, "share", dependency, "bin"))
