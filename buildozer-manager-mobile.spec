[app]
title = SIGE MPE Manager Mobile
package.name = sigempemanager
package.domain = mz.sigempre
source.dir = .
source.include_exts = py,kv,json,ttf,png,jpg,jpeg,atlas,txt
source.exclude_dirs = .git,.github,.venv,.pytest_cache,.tmp_testes,.vscode,loja,loja_bak_pre_kivymd_restore,loja_legacy,loja_py314_broken_20260325,build,dist,releases,temp,tmp,tests,admin,manager,server,api,pdfs,AI,ui,waitress,data,config,logs,Recibos,Relatorios,Relatórios,scripts,docs,utils/hardware,utils/ai
version = 1.1.0
requirements = python3,kivy==2.3.1,kivymd==1.2.0,requests==2.32.3,urllib3==2.3.0,certifi==2025.1.31,charset-normalizer==3.4.1,idna==3.10,typing_extensions==4.14.1
orientation = portrait
fullscreen = 1

# A câmara nao e declarada enquanto o leitor nativo CameraX/ML Kit nao for
# integrado. Nesta versao, leitores USB/Bluetooth HID funcionam como teclado.
android.permissions = INTERNET
android.api = 33
android.minapi = 24
android.ndk_api = 24
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = 0
android.private_storage = True

[buildozer]
log_level = 2
warn_on_root = 1
