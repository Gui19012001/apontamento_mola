[app]

title = Apontamento Roteiro TESTE
package.name = apontamentoroteiroteste
package.domain = br.com.ibero

source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,json,txt,env,zpl,xml
source.exclude_dirs = .git,.github,__pycache__,bin,.buildozer,venv

version = 0.1.0

# IMPORTANTE:
# Nao fixe python3 em 3.11.x aqui. O python-for-android usa a mesma versao
# para python3 e hostpython3. O commit p4a travado abaixo resolve o problema
# do venv/pip sem criar incompatibilidade entre as receitas.
requirements = python3,kivy==2.3.1,requests,urllib3,idna,certifi

orientation = landscape
fullscreen = 0

android.permissions = INTERNET
android.api = 34
android.minapi = 24
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

# Ambiente Android reproduzivel
android.ndk = 28c

# PR kivy/python-for-android #3360:
# limpa o venv interno e remove o "pip install -U pip" que causava
# ImportError: BuildDependencyInstallError.
p4a.branch = develop
p4a.commit = 0382d27de2f7315ed98e74884bafb30365decdee

[buildozer]

log_level = 2
warn_on_root = 0
