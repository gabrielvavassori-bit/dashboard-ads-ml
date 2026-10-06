# Devoluções: comparação entre contas e decisão do beta (03/10/2026)

## Mesma regra técnica, resultados distintos

O beta consulta `/internal/dash-ads/returns-summary` para a conta e janela selecionadas. O agente usa o mesmo coletor `_dash_ads_returns_summary` e o mesmo leitor `read_returns_snapshot` para todas as contas; não há configuração separada de classificação de devoluções para Art Paper, Passo a Passo ou Lonas Online. A identidade OAuth e o `client_id` mudam, mas o predicado de inclusão não muda. O recibo atual usa reclamações fechadas e retorno com dinheiro reembolsado, filtrados pela data do evento. Isso não é o contrato do cartão de Métricas de negócio.

| Conta e janela | Cartão Mercado Livre | Evidência do agente/beta | Conclusão |
| --- | --- | --- | --- |
| Art Paper, 03/08–01/09 | 9 vendas; R$ 1.306 | Beta exibiu 2; R$ 1.547,74, vindos de vendas de julho com retornos em agosto. | Erro de coorte comprovado; cobertura de casos também insuficiente. |
| Passo a Passo, 02/09–02/10 | 8 vendas; R$ 940 | Oito pedidos candidatos somam R$ 939,36 exatos; um deles é troca/mediação que o filtro simples omite. | Aproximação forte, mas regra de inclusão e arredondamento não certificada. |
| Lonas Online, 01/09–30/09, captura de 01/10 | 442 vendas; R$ 30.011 | Derivação técnica: 249 retornos, 250 pedidos, R$ 18.902,06. | A mesma regra explica uma parte provável da lacuna, mas não prova que os casos adicionais fecham a diferença. |

Fontes detalhadas: `RETURNS_RECONCILIATION_ARTPAPER_20261002.md` e `RETURNS_RECONCILIATION_PASSO_20261002.md` no agente, e `reports/handoff-devolucoes-mercado-livre-2026-10-01.md` na pasta de trabalho. Os totais oficiais mudam retroativamente: na janela Lonas 29/08–27/09, uma captura mostrou 395/R$ 26.873 e outra 477/R$ 31.938. Comparar só capturas da mesma janela e do mesmo instante.

## Correção aplicada no beta

O painel só aceita os dois KPIs de devolução se a ponte enviar `metric_contract=ml_business_returns_v1`, `client_id` da conta solicitada, `ok=true`, `complete=true` e a janela exata. O agente atual **não** emite esse contrato. Portanto, os cartões de devolução não são montados no beta e o aviso indica falta de conciliação. Vendas, Ads, promoções e custos/impostos não foram alterados. Os recibos técnicos antigos permanecem disponíveis para auditoria, sem serem convertidos em zero ou números oficiais.

## O que falta para liberar o contrato

1. Formar a coorte por pedidos/vendas criados na janela, com paginação e identidade completas; preservar `order_id`, `pack_id`, item, data original e valor.
2. Vincular reclamações, trocas (`/changes`), retornos (`/returns`), envios e pagamentos, inclusive eventos posteriores ao fim da janela. Não presumir que `refunded`, `cancelled`, `not_delivered` ou `related_return=0` decidam isoladamente.
3. Reconciliar, por pedido, os positivos e controles negativos da Art Paper e Passo a Passo; provar quantidade, valor e política de arredondamento contra cartões oficiais na mesma captura. Repetir na Lonas com execução limitada e retomável.
4. Só então emitir recibo versionado e testar no beta. A correção de coorte isolada não autoriza afirmar que a lacuna da Lonas foi resolvida.
