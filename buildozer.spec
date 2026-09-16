[app]

title = Apontamento Roteiro TESTE
package.name = apontamentoroteiroteste
package.domain = br.com.ibero

source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,json,txt,env,zpl,xml
source.exclude_dirs = .git,.github,__pycache__,bin,.buildozer,venv

version = 0.1.0

# Nao fixe python3 em 3.11.x aqui.
# O python-for-android deve manter python3 e hostpython3 na mesma versao.
requirements = python3,kivy==2.3.1,requests,urllib3,idna,certifi

orientation = landscape
fullscreen = 0

android.permissions = INTERNET
android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

# Versao recomendada pelo p4a usado neste projeto.
android.ndk = 28c

# Commit do python-for-android que contem:
# - correcao do venv/pip que causava BuildDependencyInstallError (#3360)
# - correcao da instalacao de wheels Android, incluindo charset-normalizer (#3366)
p4a.branch = develop
p4a.commit = 5865575d81d53617784428ee29f57be2716311ea

[buildozer]

log_level = 2
warn_on_root = 0
