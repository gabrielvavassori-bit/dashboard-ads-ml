# Dashboard ADS Mercado Livre — versão online

App Python que gera dashboards de ADS do Mercado Livre a partir de duas planilhas (vendas + publicidade), agora rodando como serviço web protegido por login e amarrado à assinatura do cliente na Eduzz.

## O que esta versão tem a mais

- **Login por email + senha**, sessão única por usuário (não dá pra repassar credencial — se outra pessoa logar, a sua sessão cai)
- **Webhook da Eduzz v3** com validação HMAC-SHA256, processa criação/renovação/cancelamento de assinatura
- **Painel admin** em `/admin` pra listar clientes, resetar senha, suspender/ativar
- **Persistência em SQLite** (não exige banco externo) com volume persistente
- **Healthcheck** em `/healthz` para o Render/Railway
- **Limite de upload** configurável e serialização de geração de dashboard pra não estourar memória
- **Zero dependências externas** — só biblioteca padrão do Python

## Arquitetura

```
[Cliente] ──→ HTTPS ──→ [App Python (Render/Railway)] ──→ SQLite no disco persistente
                                ▲
                                │ (POST /webhook/eduzz, assinado com HMAC)
                                │
                        [Eduzz Orbita]  ←── compra/renovação/cancelamento
```

## Estrutura do projeto

```
dashboard-ads-ml/
├── app.py                       # servidor HTTP principal
├── gerar_dashboard_ads_ml.py    # geração do dashboard (já existia, com 1 ajuste)
├── auth.py                      # hash de senha, sessão única, cookies
├── db.py                        # SQLite (users, sessions, webhook_events, admins)
├── webhook.py                   # handler do webhook Eduzz
├── templates.py                 # HTML de login/cadastro/admin
├── assets/
│   └── logo-un-clic.png         # SOBRESCREVA com seu logo real
├── requirements.txt             # vazio (stdlib)
├── Procfile                     # Railway/Heroku
├── render.yaml                  # Render Blueprint
├── .env.example                 # template de variáveis de ambiente
├── .gitignore
└── README.md
```

---

## Roteiro de deploy

### 1) Subir o código no GitHub

```bash
cd dashboard-ads-ml
git init
git add .
git commit -m "primeira versao online"
git branch -M main
git remote add origin git@github.com:SEU_USUARIO/dashboard-ads-ml.git
git push -u origin main
```

> Importante: substitua `assets/logo-un-clic.png` pelo seu logo de verdade antes do commit.

### 2) Provisionar no Render (recomendado)

1. Acesse https://render.com e crie conta (pode logar com GitHub).
2. Clique em **"New +" → "Blueprint"**.
3. Selecione o repositório `dashboard-ads-ml`.
4. O Render vai ler o `render.yaml` automaticamente. Você verá um formulário pedindo as variáveis marcadas `sync: false`.
5. Preencha:
   - `APP_PUBLIC_URL` → vai ser a URL do Render no formato `https://dashboard-ads-ml.onrender.com`. Você pode trocar por domínio próprio depois.
   - `EDUZZ_WEBHOOK_SECRET` → veja o passo 4 logo abaixo.
   - `EDUZZ_PRODUCT_IDS` → deixe em branco por enquanto.
   - `ADMIN_EMAIL` → seu email.
   - `ADMIN_PASSWORD` → uma senha forte (mínimo 6 chars). **Anote em gerenciador de senhas.**
6. Confirme o deploy. Primeira build leva ~2 minutos.
7. Quando subir, acesse `https://SUA_URL.onrender.com/admin/login` e entre com os dados acima.
8. **Por segurança**: depois de confirmar que está dentro, vá em "Environment" no Render e **remova** o `ADMIN_PASSWORD`. O hash da senha já está salvo no banco; ele só é usado para criar/atualizar. Sem ele setado, ninguém consegue trocar a senha do admin pelo `.env`.

> **Alternativa Railway**: praticamente idêntico. Importe o repo, configure as mesmas variáveis no painel, adicione um Volume montado em `/var/data` e seta `DATA_DIR=/var/data`.

### 3) Domínio próprio (opcional, mas recomendado)

No Render → "Settings" → "Custom Domains" → adicione `dashboard.unclicmarketplace.com.br`. Ele te dá um CNAME para apontar no Registro.br. Quando ativar, troque o `APP_PUBLIC_URL` para a URL com seu domínio.

### 4) Configurar webhook na Eduzz

1. Acesse https://integrations.eduzz.com/webhook/configs (logado na sua conta Eduzz).
2. Aba **"Chaves de acesso"** → **"+ Nova chave"**. Dê um nome (ex: `dashboard-ads-ml`) e copie o valor gerado.
3. Cole esse valor como `EDUZZ_WEBHOOK_SECRET` no Render (Environment → save → o app reinicia sozinho).
4. Volte para **"Configurações"** → **"+ Nova configuração"**:
   - **Nome**: `dashboard-ads-ml`
   - **Chave de acesso**: a que você criou no passo 2
   - **URL**: `https://SUA_URL/webhook/eduzz`
   - **Eventos**: marque pelo menos
     - `myeduzz.invoice_paid`
     - `myeduzz.invoice_refunded`
     - `myeduzz.invoice_canceled`
     - `myeduzz.invoice_expired`
     - `myeduzz.contract_created`
     - `myeduzz.contract_updated`
5. Clique em **"Verificar URL"**. Tem que vir status 200 (pode dar 401 se o secret ainda não foi atualizado no Render — espere 1 minuto após salvar).
6. Salve e **ative** a configuração. A Eduzz vai enviar um ping fake; se a app responder 200, a integração fica verde.

### 5) Configurar a oferta na Eduzz

Crie (ou edite) o produto na Eduzz como **Assinatura mensal/anual**. Na seção de "entrega" / email pós-compra do produto, adicione esta mensagem para o cliente:

> Obrigado pela compra! Para acessar o Dashboard ADS Mercado Livre:
>
> 1. Acesse: https://dashboard.unclicmarketplace.com.br/cadastrar
> 2. Use **exatamente o mesmo email** que você informou nesta compra
> 3. Defina sua senha de acesso
> 4. Pronto! Sua sessão fica ativa enquanto a assinatura estiver em dia.

> Importante: a sessão é única por dispositivo. Se você logar em outro lugar, a sessão anterior cai.

### 6) Operação no dia a dia

- **Cliente compra** → Eduzz dispara `myeduzz.invoice_paid` ou `contract_created` → seu app cria o user com status `active`.
- **Cliente acessa `/cadastrar`** → cria senha → entra.
- **Renovação mensal** → Eduzz dispara `invoice_paid` novo → seu app estende `expires_at`.
- **Cliente cancela / não paga** → Eduzz dispara `invoice_canceled`/`invoice_expired` ou `contract_updated` com status `canceled`/`late` → seu app suspende.
- **Cliente esqueceu a senha** → você entra em `/admin`, busca pelo email, clica "Resetar senha". Isso derruba sessões ativas e libera ele para cadastrar nova senha em `/cadastrar`.

### 7) Backup do banco

O SQLite fica em `/var/data/app.db` (no Render). Para baixar manualmente:

```bash
# Pelo Shell do Render:
cp /var/data/app.db /tmp/app.db
```

Considere rodar um cron mensal copiando para um bucket (S3, R2 ou Google Drive via rclone). Para 50+ clientes, o arquivo deve passar de poucos MB.

---

## Desenvolvimento local

```bash
cd dashboard-ads-ml
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
cp .env.example .env       # edite com seus valores

# Defina as variaveis (Linux/Mac):
export $(cat .env | xargs)
# Windows PowerShell:
# Get-Content .env | ForEach-Object { $n,$v = $_ -split '=',2; Set-Item -Path "Env:$n" -Value $v }

python app.py
```

Acesse http://127.0.0.1:4182. O webhook só vai aceitar requisições com `x-signature` HMAC válido — para testar localmente:

```bash
BODY='{"id":"test-1","event":"myeduzz.invoice_paid","data":{"buyer":{"email":"teste@cliente.com","name":"Teste","id":"123"}}}'
SECRET="cole_o_mesmo_EDUZZ_WEBHOOK_SECRET"
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -r | cut -d' ' -f1)
curl -X POST http://127.0.0.1:4182/webhook/eduzz \
  -H "Content-Type: application/json" \
  -H "X-Signature: $SIG" \
  -d "$BODY"
```

Depois é só logar em `/cadastrar` com `teste@cliente.com`.

---

## FAQ rápido

**E se o cliente passar o login pra outra pessoa?**
A sessão é única por conta. Quando o "convidado" logar, o original cai imediatamente. Em alguns segundos o original vai notar e mudar a senha — e você ainda fica com o log no `audit_log`.

**Quanto custa rodar isso?**
Render Starter US$ 7/mês + disco 1 GB US$ 0.25/mês ≈ US$ 7.25/mês. Suporta tranquilo 50+ clientes ativos com o uso intermitente típico de gerador de dashboard. Quando passar de ~200 clientes simultâneos, pode ser interessante migrar para o Standard (US$ 25/mês) ou trocar pra Postgres.

**Posso adicionar email transacional depois?**
Sim. Quando quiser, integre algo como Resend ou Brevo no `webhook.py` e no `/cadastrar` para enviar magic links automáticos. A arquitetura já permite, é só plugar.

**E se a Eduzz mudar o nome dos eventos?**
A doc oficial é https://developers.eduzz.com/docs/webhook. Se algum nome mudar, atualize as listas `activate_events` / `revoke_events` em `webhook.py`.
