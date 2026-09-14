# Proteções antirregressão

- Antes de alterar comportamento com regressão conhecida, consulte `regressions/manifest.json` por arquivo, componente, domínio e tags e execute as proteções associadas.
- Uma tarefa não pode ser declarada concluída, enviada à branch publicada ou implantada enquanto uma regressão crítica relacionada estiver falhando.
- O catálogo canônico e a Skill `$marketplace-antiregression` ficam no `MARKETPLACE GOVERNANCE`; o manifesto local associa as regras aos testes executáveis deste repositório.
