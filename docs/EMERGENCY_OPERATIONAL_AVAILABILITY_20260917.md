# Dash Ads operacional — exceção autorizada

- ID: DASH-ADS-OPERATIONAL-AVAILABILITY-20260917
- Data: 2026-09-17
- Classificação: COMPARTILHADA (Dashboard Ads e agente-ml).
- Origem: autorização explícita de Gabriel para restaurar consulta parcial.
- Agentes impactados: desenvolvedores do Dashboard Ads produção/beta e agente-ml.
- Regra: o Dash principal consulta fatos disponíveis por conta/período, sem depender de Billing ou certificado de completude. Aviso de dados parciais obrigatório; divergência de 5% não é presumida.
- Inteligência financeira mantém validação estrita. Não liberar contas erradas, datas diferentes ou inventar dados.
- Arquivos: app.py, regressions/manifest.json, test_operational_availability.py; agente: dash_ads_operational.py.
- Quem/quando consulta: agentes antes de modificar/publicar leitor operacional ou validação de integridade.
- Altera comportamento: sim, substitui bloqueio global por consulta parcial explicitamente identificada no Dash principal.
- Evidência local: testes de renderização parcial, identidade, período, ausência de dados e isolamento da inteligência financeira.
- Status: C — implementação local; publicação e validação autenticada ainda pendentes.
