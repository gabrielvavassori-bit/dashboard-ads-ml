# Ambiente beta espelhado

## Objetivo

O beta permite testar o mesmo usuario Eduzz e a mesma conta Mercado Livre autorizada, mas em um servico Render separado da producao. A versao beta deve ter codigo, banco, cache, logs e deploy proprios.

## Estado desta estrutura

- `/teste` existe somente quando `BETA_MODE=true`.
- O acesso exige sessao local e email presente em `BETA_ALLOWED_EMAILS`.
- Eventos de cobranca e entrega Eduzz retornam bloqueio no beta.
- A conta ML local do usuario e apenas exibida; ela nao e copiada para outro banco.
- A ponte de identidade esta implementada em `beta_bridge.py`: a producao envia ao beta uma assercao HMAC de uso unico, com validade curta e apenas identidade, plano, validade e metadados nao secretos da conta ML.
- O beta cria uma sessao e um registro de usuario proprios a partir dessa assercao; o cookie de sessao nunca atravessa os servicos.
- O blueprint separado esta em `render-beta.yaml`.
- A ponte usa `BETA_SHARED_AUTH_URL`, `BETA_SHARED_AUTH_SECRET`, `BETA_PUBLIC_URL` e `BETA_SHARED_ML_URL`. O segredo compartilhado deve ser criado separadamente no Render, nunca versionado.

## Regra de espelhamento

Nao copiar cookies, senhas, access tokens, refresh tokens ou `app.db` entre servicos. O fluxo usa uma assercao assinada e curta, contendo identidade, expiracao e metadados operacionais nao secretos; o beta cria sua propria sessao e consulta o fornecedor autorizado.

## Aceite antes de publicar

1. Producao continua com `/teste` indisponivel.
2. Beta sem allowlist retorna 403.
3. Usuario allowlisted abre `/teste`.
4. Webhook e entrega Eduzz do beta retornam 404 e nao alteram assinaturas.
5. `/healthz` retorna 200 no servico beta.
6. Nenhum segredo aparece no HTML, resposta ou log.
7. O mesmo usuario e conta ML sao reconciliados por identificador central, sem duplicar credenciais.
8. Uma assercao adulterada, expirada ou reutilizada e recusada.
9. O beta continua acessivel somente por allowlist; ele nao vira um ambiente publico de teste.

## Implantacao controlada pendente

O codigo e os testes da ponte estao prontos localmente. Ainda faltam a criacao do segundo servico no Render, a configuracao manual dos enderecos/segredo em ambos os servicos, o deploy controlado e a prova online com uma conta autorizada. A producao so precisa receber as rotas de autorizacao; ela continua com o beta desligado por padrao.
