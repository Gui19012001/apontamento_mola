# APK - Apontamento por Roteiro TESTE

APK Kivy de homologação.

## Operador informa apenas
- OP
- Operação
- Quantidade

O APK consulta o roteiro automaticamente e envia:

```json
{
  "op": "x0222601020",
  "roteiro": "03",
  "operac": 20,
  "quant": 20,
  "lote": ""
}
```

## Histórico local
SQLite no próprio tablet:
- APONTADO
- ERRO
- VERIFICAR

ERRO permite REAPONTAR. VERIFICAR exige confirmação manual, porque timeout não prova que o TOTVS deixou de gravar.

## API
Base:
`http://192.168.2.15:8195/rest/apontmod2`

Consulta esperada:
`GET /get_id?op=<OP>`

Inclusão:
`POST /new`

Para resolver o roteiro automaticamente, o GET precisa retornar um campo como `roteiro`, `G2_CODIGO` ou equivalente. Também pode retornar linhas por operação.

Se o endpoint do TI usar `get_id?=<OP>`, altere no workflow/teste.env:

```env
TOTVS_GET_ID_MODE=raw
```

## GitHub Secrets
Crie em `Settings > Secrets and variables > Actions`:
- `TOTVS_USERNAME`
- `TOTVS_PASSWORD`
- `TOTVS_TENANT_ID` (se utilizado)

## Build
Estrutura mantida no padrão dos APKs estáveis:
- Ubuntu 24.04
- Python 3.11
- Java 17
- Kivy 2.3.1
- Android API 34
- Min API 24
- arm64-v8a + armeabi-v7a
- INTERNET
- Buildozer
- cython<3

Execute:
`Actions > Build Android APK > Run workflow`

O artifact gerado chama:
`apontamento-roteiro-teste-apk`
