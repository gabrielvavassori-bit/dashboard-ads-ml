# Etapa 4 — cobertura parcial no gráfico

Escopo: principal e demo, mesmo renderizador. Sem mudanças no beta, coletas, métricas da tabela ou etapa 5.

O leitor operacional não entrega prova diária de completude. Por isso todos os pontos dessa origem recebem cobertura não comprovada, sem presumir que ter uma linha significa ter o universo inteiro. Os valores disponíveis são preservados. A presença separada de Ads/vendas controla N/D no gráfico e tooltip; datas sem linhas são marcadas sem dados, não barras zero. Médias e tendências são omitidas em séries parciais, com explicação visível. Contratos completos continuam com apresentação normal.

Proteção: REGRESSION-001, testes em test_operational_availability.py.
Prova local: guard crítico (16 testes) passou antes da última extensão de datas; executar novamente antes de publicar. Browser Chromium 390/768/1440: sem erros JS, receita preservada, Ads ausente sem barra, N/D no tooltip e nenhuma média parcial.

Suíte ampla: 121 testes, 32 falhas e 1 erro. Reexecução da versão HEAD sem a alteração reproduziu as falhas de fixtures/integração preexistentes. Não são declaradas como corrigidas nesta etapa.

Limitação: cobertura operacional desconhecida não permite distinguir dias realmente completos sem ampliar o contrato de origem. Aviso conservador intencional, não certificado de falta.
