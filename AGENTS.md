# Regras do Dashboard Ads

## Excecao operacional autorizada em 2026-09-17

Consultar `docs/EMERGENCY_OPERATIONAL_AVAILABILITY_20260917.md` e o manifest antes de alterar o gate. O Dash principal abre com cache parcial explicitamente sinalizado, da conta e periodo exatos; Billing/completude nao bloqueiam essa consulta. A inteligencia financeira continua estrita. Esta regra substitui a exigencia geral de bloqueio do Dash principal abaixo.

## Protecao antirregressao

- Antes de alterar comportamento com regressão conhecida — especialmente cache online, snapshots diários, períodos, KPIs, exportações, recomendações financeiras ou integração com `agente-ml` — consulte `regressions/manifest.json` por arquivo, componente, domínio e tags e execute as proteções associadas.
- O hook `Stop` em `.codex/hooks.json` examina o diff pendente e chama o seletor automaticamente ao encerrar um turno. Ele executa somente as proteções relacionadas; `FAIL`, `VALIDATION ERROR`, `NOT RUN` ou ausência de evidência nunca equivalem a `PASS`.
- Execute `scripts/regression_guard.py` antes da publicação e com `--run` depois da alteração. Uma regressão crítica relacionada bloqueia conclusão, push para a branch publicada e deploy enquanto qualquer proteção falhar ou estiver ausente. FAST CHECK: `python scripts/regression_guard.py --changed-file <arquivo>`; FULL REGRESSION CHECK: repita com `--run`.
- O catálogo canônico e a Skill `$marketplace-antiregression` ficam no `MARKETPLACE GOVERNANCE`; o manifesto local associa as regras aos testes executáveis deste repositório.
- Não trate memória, texto, `/healthz` ou cache legado como prova de integridade financeira. A validação de produção exige a revisão ativa e uma execução funcional autenticada.

## REGRESSION-001

Nenhum KPI, exportação, recomendação ou tabela financeira pode ser exibido se a conta e o período exatos não tiverem cobertura comprovada de Ads e vendas. Ausência não pode virar zero sem evidência. Um contrato incompleto deve bloquear a saída financeira, inclusive quando houver cache de outro período.
