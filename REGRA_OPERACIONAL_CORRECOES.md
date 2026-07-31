# Regra operacional de correcoes - un-clic-ia

Esta regra vale para todo o projeto `un-clic-ia`, especialmente para o Dashboard ADS Mercado Livre em producao.

Sempre que houver uma correcao, ajuste ou hotfix, o fechamento da tarefa deve informar explicitamente um destes estados:

1. `commit + push + deploy` executados e validados.
2. Correcao validada localmente, mas ainda nao subida, perguntando se deve fazer `commit + push + deploy`.
3. Correcao nao subida por bloqueio, informando claramente o motivo e o que falta para subir.

Nenhuma correcao deve ser apresentada como concluida se ela ainda estiver apenas local.

Para alteracoes que afetam cliente, Eduzz, Render, login, OAuth, dados financeiros, leitura online, deduplicacao ou calculos do dashboard:

- rodar testes antes do commit;
- validar o artefato/endpoint real depois do deploy;
- informar commit, push, deploy e evidencia de validacao;
- se nao subir, dizer explicitamente que nao subiu.

Origem da regra: decisao humana de Gabriel Vavassori em 31/07/2026, apos uma correcao local ser validada sem ter sido publicada automaticamente.
