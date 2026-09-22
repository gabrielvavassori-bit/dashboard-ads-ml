# Protótipo beta — custos, embalagem e central de promoções

## Objetivo

Transformar o Dashboard Ads beta em uma ferramenta de decisão comercial por produto. O usuário poderá registrar custo e embalagem, validar as recomendações de medidas do Mercado Livre e avaliar a margem antes de participar, alterar ou sair de uma promoção.

O escopo permanece exclusivamente no beta. Nenhuma ação promocional em lote, criação de campanha ou publicação no Dashboard principal será liberada antes das validações descritas neste documento.

## Resultado esperado

Para cada produto ou anúncio, o beta deve responder com clareza:

1. Qual é o custo unitário informado para aquele produto?
2. Quais são as medidas e o peso reais da embalagem?
3. O que está cadastrado no anúncio Mercado Livre confere com a embalagem real?
4. A recomendação do Mercado Livre para corrigir medida ou peso procede, não procede, ou não pode ser validada?
5. Qual é a margem antes de imposto, após imposto e após Ads?
6. Qual será a margem projetada se o produto entrar na promoção proposta?
7. A promoção foi apenas simulada, confirmada pelo usuário ou comprovadamente aplicada pelo Mercado Livre?

## Princípios obrigatórios

- O custo, peso e medidas preenchidos pelo usuário são dados persistentes da conta, não dados temporários do navegador.
- A interface mostra SKU para facilitar o uso, mas a persistência também precisa guardar a identidade MLB/MLBU. SKU isolado pode mudar, ficar vazio ou se repetir.
- Nenhum campo financeiro ausente vira zero. A interface deve mostrar `N/D` ou `informação insuficiente`.
- `MC projetada` é uma simulação anterior à venda. `MC realizada` usa os lançamentos financeiros efetivos após a venda.
- Uma indicação do Mercado Livre para alterar peso ou medidas é uma recomendação a validar, não prova de erro do anúncio.
- Alterações reais de promoção continuam em duas etapas: prévia e confirmação explícita.
- Um estado de confirmação incerto nunca pode ser reenviado automaticamente.

## Arquitetura proposta

```text
Dados do produto
  ├─ MLB e MLBU vindos da conta Mercado Livre
  ├─ SKU exibido ao usuário
  ├─ custo unitário informado
  └─ peso e medidas reais da embalagem
             │
             ▼
SQLite persistente por usuário + conta ML
             │
             ├─ perfil de custo existente
             ├─ cadastro de embalagem
             ├─ histórico de alterações
             └─ leituras de promoção e auditoria de confirmação
             │
             ▼
Dashboard Ads beta
  ├─ Produtos e custos
  ├─ Embalagem e validação logística
  ├─ Central de promoções por conta
  └─ Promoções do anúncio
```

## Tela 1 — Produtos e custos

Local: nova aba principal do beta, independente da tabela operacional de Ads.

Campos por linha:

| Campo | Fonte | Edição |
|---|---|---|
| Imagem, título, SKU, MLB, MLBU | Conta Mercado Livre / cache Dash Ads | Somente leitura |
| Custo unitário | Usuário | Editável |
| Imposto da conta | Perfil financeiro | Editável no perfil da conta |
| Logística | Anúncio Mercado Livre | Somente leitura |
| Margem histórica | Financeiro Inteligência de Vendas | Somente leitura |
| Status de custo | Calculado | Somente leitura |

Comportamentos:

- busca por título, SKU, MLB e MLBU;
- filtro de produtos sem custo, custo desatualizado e margem negativa;
- salvamento imediato com indicação de data e usuário da alteração;
- custo pode ser herdado de um produto pai somente mediante escolha explícita;
- alteração do custo gera histórico, para que uma análise de período não perca rastreabilidade.

### Persistência

O beta já possui `intelligence_cost_profiles`, com custo por SKU e chave estável, associado a `user_id` e `client_id`. A primeira fase pode usar essa estrutura existente. Para uma versão robusta, criar tabela normalizada de custos com:

```text
user_id, client_id, identity_type, identity_value,
sku_display, unit_cost, source, updated_at, updated_by
```

`identity_type` aceita `mlbu`, `mlb`, `sku` e `family`. A resolução prioriza MLBU, depois MLB e por último SKU.

## Tela 2 — Embalagem e validação logística

Local: detalhe de cada produto dentro de Produtos e custos; resumo também disponível no modal do anúncio.

Campos preenchidos pelo usuário:

```text
altura_cm
largura_cm
comprimento_cm
peso_real_kg
origem_da_medicao: balança, fabricante, embalagem conferida
data_da_conferência
observação
```

Dados lidos do Mercado Livre:

```text
medidas declaradas no anúncio, quando retornadas
peso declarado, quando retornado
modalidade logística e atributos relevantes do item
indicações ou alertas apresentados pelo Mercado Livre, quando disponíveis
```

Resultado da validação:

| Estado | Significado |
|---|---|
| Confere | Medida/peso real e declaração do anúncio coincidem dentro da tolerância definida |
| Divergente | Há diferença comprovada entre embalagem real e anúncio |
| Indicação não comprovada | O Mercado Livre recomenda revisão, mas os dados reais conferem com o anúncio |
| Não validável | Falta medida/peso real, dado declarado ou identificação do anúncio |

O painel não afirma que o Mercado Livre calculou frete errado. Seu papel é responder se a recomendação de correção é compatível com o produto físico registrado.

### Peso cubado

O sistema calculará volume e, se houver fator aplicável confirmado para a modalidade logística, poderá exibir peso cubado de referência. Sem regra confirmada do Mercado Livre para aquele contexto, o campo deve ser identificado como `estimativa interna`, nunca como peso oficial utilizado pelo Mercado Livre.

O histórico financeiro permanece útil como sinal posterior: custos de medida e diferenças de peso podem apontar para uma divergência que merece conferência, mas não são prova isolada de erro cadastral.

## Tela 3 — Central de promoções da conta

Local: nova aba beta `Central de promoções`.

Subabas:

1. **Por campanha**: campanhas disponíveis, período, tipo e produtos candidatos.
2. **Por anúncio**: todas as promoções aplicáveis a um MLB específico.
3. **Minhas promoções**: participantes, agendadas e encerradas.

Campos de decisão por item:

| Campo | Origem |
|---|---|
| Preço atual e promocional | Mercado Livre |
| Limite mínimo e máximo | Mercado Livre |
| Participação do Mercado Livre | Mercado Livre, quando retornada |
| Desconto do vendedor | Mercado Livre / cálculo da proposta |
| Custo unitário | Cadastro de custos |
| Imposto | Perfil financeiro |
| MC antes de imposto | Cálculo do beta |
| MC após imposto | Cálculo do beta |
| TACOS observado | Dash Ads |
| MC após Ads | Cálculo do beta |
| Situação da embalagem | Cadastro e validação logística |

## Regra de margem

Os nomes precisam separar cada camada financeira:

```text
Receita do produto
(-) tarifa/comissão e encargos Mercado Livre
(-) frete e ajustes conhecidos
(-) custo unitário do produto
= MC antes de imposto
(-) imposto da conta
= MC após imposto
(-) investimento Ads atribuído ou alocado
= MC após Ads
```

Para promoções, a prévia substitui a receita pelo preço promocional e incorpora o subsídio do Mercado Livre quando a API o informar.

Rótulos obrigatórios:

- `MC realizada`: calculada a partir de lançamentos financeiros encerrados;
- `MC projetada`: estimativa antes de entrar ou alterar uma promoção;
- `MC parcial`: há campos financeiros disponíveis, mas algum custo obrigatório está ausente;
- `N/D`: não há base suficiente para cálculo responsável.

## Fluxo de promoção individual

1. Usuário abre um anúncio ou uma campanha.
2. Beta consulta a elegibilidade e os limites atuais no Mercado Livre.
3. Usuário informa preço e, quando exigido, estoque ou período.
4. Beta mostra a prévia financeira e logística.
5. Usuário confirma explicitamente a ação real.
6. Agente envia a solicitação ao Mercado Livre.
7. Agente consulta novamente o anúncio para comprovar o resultado.
8. Beta registra auditoria com conta, MLB, promoção, preço, data, resultado e estado de confirmação.

Estados de ação:

| Situação | Ação exibida |
|---|---|
| Candidato elegível | Participar desta campanha |
| Participante | Alterar esta promoção / Sair desta promoção |
| Requer preço ou estoque | Configurar participação |
| Dados insuficientes para MC | Participar com aviso financeiro explícito; proibido em lote |
| Confirmação incerta | Consultar estado; nunca reenviar automaticamente |

## Ações em lote

Não entram na primeira entrega transacional.

Pré-requisitos:

- fluxo individual comprovado em múltiplas modalidades;
- prévia válida para cada item;
- bloqueio de itens sem MC calculável;
- resultado individual por item, incluindo falha parcial;
- idempotência e auditoria;
- nova consulta após cada alteração ou lote controlado.

## Etapas de implantação

### Etapa 0 — Recuperar a base promocional do beta

Objetivo: restaurar os fluxos aprovados de participar, alterar, sair e confirmação, além da validação pelo preço-base correto.

Validação:

- leitura de promoções por anúncio;
- prévia sem escrita;
- confirmação única;
- reconsulta comprovando resultado;
- tentativa repetida não duplica operação;
- erro da API apresenta motivo legível.

Critério para avançar: nenhuma operação real é liberada enquanto a regressão atual de promoção persistir.

### Etapa 1 — Cadastro persistente de custo

Objetivo: disponibilizar Produtos e custos no beta.

Implementação:

- reaproveitar a persistência financeira existente;
- criar a interface de busca e edição;
- persistir custo por identidade estável;
- registrar data, origem e histórico.

Validação:

- custo continua disponível após logout, login e reinício do serviço;
- custo de uma conta não aparece em outra;
- variação não recebe custo de produto diferente por erro de SKU;
- campos ausentes retornam N/D.

### Etapa 2 — Margem histórica por produto

Objetivo: exibir MC realizada a partir de vendas financeiras encerradas.

Implementação:

- reutilizar receita, tarifas, fretes, ajustes, reembolsos e custos já persistidos;
- aplicar imposto configurado no perfil;
- apresentar camadas de margem, incluindo MC após Ads.

Validação:

- comparar uma amostra de pedidos com o detalhamento financeiro oficial;
- conferir custo unitário, tarifa e imposto;
- validar que devoluções e cancelamentos não entram como vendas concluídas;
- deixar explícito qualquer dado incompleto.

### Etapa 3 — Cadastro e validação de embalagem

Objetivo: comparar embalagem física registrada com declaração do anúncio e indicação do Mercado Livre.

Implementação:

- tabela persistente de embalagem por identidade estável;
- leitura dos dados de envio do item;
- comparação com tolerância configurada;
- estados Confere, Divergente, Indicação não comprovada e Não validável.

Validação:

- casos iguais, divergentes e incompletos;
- produto com variações de tamanhos diferentes;
- produto Full e não Full, se disponíveis;
- nenhuma conclusão automática a partir de custo de frete isolado.

### Etapa 4 — Prévia financeira de promoções

Objetivo: integrar custo, imposto e embalagem à decisão promocional individual.

Implementação:

- ampliar o payload de leitura de promoções;
- preservar preço, limites, modalidade, status e subsídios retornados;
- calcular MC projetada no preço proposto;
- exibir aviso quando custo ou logística estiverem pendentes.

Validação:

- comparação com campanhas ativas e candidatas no painel Mercado Livre;
- preço mínimo/máximo respeitado;
- subsídio exibido apenas quando retornado pela API;
- MC projetada distinguida da MC realizada;
- prévia nunca escreve no Mercado Livre.

### Etapa 5 — Operações individuais de promoção

Objetivo: liberar participar, alterar e sair para modalidades comprovadas.

Implementação:

- prévia assinada com expiração;
- CSRF, identidade de conta e MLB revalidados;
- confirmação explícita;
- auditoria persistente e reconsulta após escrita.

Validação:

- cenário de sucesso;
- rejeição por regra do Mercado Livre;
- mudança de preço entre prévia e confirmação;
- token de prévia expirado;
- confirmação incerta sem reenvio;
- resultado visível no painel Mercado Livre.

### Etapa 6 — Central de promoções por conta

Objetivo: permitir análise por campanha com candidatos e participantes.

Implementação:

- coletor em leitura para campanhas e anúncios elegíveis;
- filtros por status e busca por SKU/MLB/título;
- resumo financeiro e logístico por linha;
- sem ações em lote nesta primeira versão.

Validação:

- total e status comparados ao painel Mercado Livre em amostra de contas;
- paginação completa comprovada;
- conta selecionada isolada de outras contas;
- ausência de dados não vira campanha vazia ou valor zero.

### Etapa 7 — Ações em lote e campanhas do vendedor

Objetivo: somente após validação das etapas anteriores, adicionar ações massivas, criação de cupom e criação de campanha.

Validação:

- prévia e confirmação item a item;
- relatório de sucesso, rejeição e estado incerto;
- sem repetição automática;
- amostra real aprovada antes de ampliar o uso.

## Segurança e governança

- Beta isolado do Dashboard principal.
- Banco separado por usuário e conta Mercado Livre.
- Nenhum token Mercado Livre é enviado ao navegador.
- Toda escrita promocional registra auditoria.
- Ações em lote exigem resultado individual, não apenas sucesso agregado.
- Dados financeiros incompletos impedem leitura de margem como se fosse completa.
- Antes de cada mudança de coleta, cache ou cálculo financeiro, executar as proteções de regressão aplicáveis ao Dash Ads.

## Critério para migrar ao Dashboard principal

A migração só poderá ser proposta depois de:

1. custos persistentes comprovados em contas beta;
2. margem histórica comparada com amostra financeira real;
3. validação de embalagem em produtos com e sem divergência;
4. promoções individuais comprovadas no Mercado Livre;
5. inexistência de regressão crítica aberta;
6. validação visual desktop e celular;
7. deploy beta e revisão Render confirmados.

## Fora do escopo inicial

- Alterar automaticamente peso ou medidas no Mercado Livre.
- Declarar que o Mercado Livre calculou frete incorretamente.
- Ações promocionais em massa na primeira entrega.
- Publicar no Dashboard principal antes da validação beta.
