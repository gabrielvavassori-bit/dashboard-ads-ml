# Beta isolado do Dashboard ADS

Este fluxo existe para testar novas versoes sem impactar o portal real de clientes.

## Objetivo

- manter o portal principal em producao
- publicar um segundo ambiente separado
- testar login, admin, online, OAuth e correcoes novas antes de subir no real

## Arquivo do beta

Use o arquivo:

`C:\Users\gabri\OneDrive\Documentos\New project\un-clic-ia\dashboard-ads-ml-production\render-beta.yaml`

## Regras seguras do beta

- service name separado: `dashboard-ads-ml-beta`
- disco separado: `dashboard-beta-data`
- `autoDeploy: false`
- acesso so por liberacao manual ou por usuarios de teste
- nao apontar webhook real da Eduzz para o beta

## Recomendacao de uso

1. Criar o servico beta no Render com esse blueprint.
2. Definir uma `APP_PUBLIC_URL` propria, por exemplo:
   - `https://dashboard-ads-ml-beta.onrender.com`
3. Usar admin e usuarios de teste separados.
4. Validar no beta:
   - login
   - cadastro de senha
   - liberacao manual por X dias
   - fluxo online
   - fluxo offline
5. So depois promover a mesma mudanca para o portal principal.

## O que nao fazer no beta

- nao reaproveitar o mesmo disco do producao
- nao trocar a URL do webhook real para o beta
- nao usar como ambiente publico aberto

## Quando usar

- novas mudancas no login
- novas mudancas no admin
- mudancas na leitura online
- testes de conciliacao API x XLSX
- qualquer ajuste que possa bloquear cliente pago
