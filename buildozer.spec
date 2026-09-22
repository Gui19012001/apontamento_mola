[app]

title = IBERO Apontamento Operacao TESTE
package.name = apontamentoroteiroteste
package.domain = br.com.ibero

source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,json,txt,env,zpl,xml
source.exclude_dirs = .git,.github,__pycache__,bin,.buildozer,venv

version = 0.5.0

# Nao fixe python3 em 3.11.x aqui.
# O python-for-android deve manter python3 e hostpython3 na mesma versao.
requirements = python3,kivy==2.3.1,requests,urllib3,idna,certifi,pyjnius

orientation = landscape
fullscreen = 0

android.permissions = INTERNET
android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

android.ndk = 28c

# Contem as correcoes do venv/pip e das wheels Android.
p4a.branch = develop
p4a.commit = 5865575d81d53617784428ee29f57be2716311ea

[buildozer]

log_level = 2
warn_on_root = 0
