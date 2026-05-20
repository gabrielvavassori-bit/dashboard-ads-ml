# 🚀 Guia de Deploy Automático - Dashboard ADS ML

**Objetivo**: Colocar seu app online em 3 passos, com acesso protegido por Eduzz.

---

## 📋 Pré-requisitos

- ✅ Conta no GitHub (gratuita)
- ✅ Conta no Render.com (US$ 7/mês para produção)
- ✅ Acesso à sua conta Eduzz (para webhook)

---

## 🎯 Passo 1: Criar repositório no GitHub

### O que você precisa fazer:

1. Acesse **https://github.com/new**
2. Crie um repositório chamado `dashboard-ads-ml`
3. Escolha **Public** (para o Render conseguir acessar)
4. Clique em **"Create repository"**

### Depois, copie e cole no seu terminal:

```bash
cd /home/ubuntu/dashboard-ads-ml

# Adicionar repositório remoto (SUBSTITUA SEU_USUARIO)
git remote add origin https://github.com/SEU_USUARIO/dashboard-ads-ml.git

# Renomear branch para main
git branch -M main

# Fazer push
git push -u origin main
```

**Resultado**: Seu código está no GitHub! ✅

---

## 🌐 Passo 2: Deploy no Render.com

### O que você precisa fazer:

1. Acesse **https://render.com**
2. Clique em **"Sign up"** (ou faça login se já tem conta)
3. Você pode logar com GitHub direto (recomendado)

### Depois de logado:

1. Clique em **"New +"** no canto superior direito
2. Selecione **"Blueprint"**
3. Selecione o repositório `dashboard-ads-ml`
4. Clique em **"Connect"**

### Preencha as variáveis de ambiente:

O Render vai pedir para preencher esses campos:

| Campo | Valor | Exemplo |
|-------|-------|---------|
| `APP_PUBLIC_URL` | URL pública do seu app | `https://dashboard-ads-ml.onrender.com` |
| `ADMIN_EMAIL` | Seu email | `gabriel@unclicmarketplace.com.br` |
| `ADMIN_PASSWORD` | Senha forte | `T-d230lG4v3rmCZVDxIHMQ` |
| `EDUZZ_WEBHOOK_SECRET` | Secret do webhook (veja passo 3) | `a1c0aca3ff562e910edca4374aa341ef8e3ba0e27164c6f7e4c25b6a74cc4ad7` |
| `EDUZZ_PRODUCT_IDS` | Deixe em branco por enquanto | (vazio) |

**Importante**: Você pode deixar `EDUZZ_WEBHOOK_SECRET` em branco por enquanto. Você vai preencher depois de criar a chave na Eduzz.

### Deploy:

1. Clique em **"Deploy"**
2. Espere 2-3 minutos (primeira build é mais lenta)
3. Quando terminar, você verá uma URL como `https://dashboard-ads-ml.onrender.com`

**Resultado**: Seu app está online! ✅

---

## 🔐 Passo 3: Configurar webhook na Eduzz

### Criar chave de acesso:

1. Acesse **https://integrations.eduzz.com/webhook/configs** (logado na sua conta Eduzz)
2. Clique na aba **"Chaves de acesso"**
3. Clique em **"+ Nova chave"**
4. Dê um nome (ex: `dashboard-ads-ml`)
5. **Copie o valor gerado** (esse é seu `EDUZZ_WEBHOOK_SECRET`)

### Adicionar no Render:

1. Volte para o Render: https://render.com
2. Clique no seu serviço `dashboard-ads-ml`
3. Vá em **"Environment"** (no menu lateral)
4. Procure por `EDUZZ_WEBHOOK_SECRET`
5. Cole o valor que você copiou
6. Clique em **"Save"** (o app vai reiniciar sozinho)

### Configurar webhook na Eduzz:

1. Volte para **https://integrations.eduzz.com/webhook/configs**
2. Clique em **"+ Nova configuração"**
3. Preencha:
   - **Nome**: `dashboard-ads-ml`
   - **Chave de acesso**: selecione a que você criou
   - **URL**: `https://dashboard-ads-ml.onrender.com/webhook/eduzz` (ou sua URL do Render)
   - **Eventos**: marque estes:
     - ✅ `myeduzz.invoice_paid`
     - ✅ `myeduzz.invoice_refunded`
     - ✅ `myeduzz.invoice_canceled`
     - ✅ `myeduzz.invoice_expired`
     - ✅ `myeduzz.contract_created`
     - ✅ `myeduzz.contract_updated`

4. Clique em **"Verificar URL"** (deve retornar 200 OK)
5. Clique em **"Salvar"** e depois **"Ativar"**

**Resultado**: Webhook configurado! ✅

---

## 📧 Passo 4: Configurar produto na Eduzz

### Criar/editar produto:

1. Acesse sua conta Eduzz
2. Vá para **"Meus Produtos"** ou crie um novo
3. Configure como **Assinatura mensal/anual**
4. Na seção de **"Email pós-compra"** (ou "Entrega"), adicione:

```
Obrigado pela compra! Para acessar o Dashboard ADS Mercado Livre:

1. Acesse: https://dashboard-ads-ml.onrender.com/cadastrar
2. Use EXATAMENTE o mesmo email que você informou nesta compra
3. Defina sua senha de acesso
4. Pronto! Sua sessão fica ativa enquanto a assinatura estiver em dia.

Importante: a sessão é única por dispositivo. Se você logar em outro lugar, a sessão anterior cai.
```

**Resultado**: Cliente recebe instruções automáticas! ✅

---

## ✅ Teste completo

### 1. Acessar painel admin:

```
https://dashboard-ads-ml.onrender.com/admin
```

Email: `gabriel@unclicmarketplace.com.br` (ou o que você configurou)
Senha: `T-d230lG4v3rmCZVDxIHMQ` (ou a que você configurou)

### 2. Simular compra na Eduzz:

Faça uma compra de teste do seu produto. Você deve ver:
- Um novo usuário aparecer no painel admin
- Status `active`
- Timestamp de criação

### 3. Cliente fazer cadastro:

1. Acesse: `https://dashboard-ads-ml.onrender.com/cadastrar`
2. Use o email da compra de teste
3. Defina uma senha
4. Faça login

**Resultado**: Fluxo completo funcionando! ✅

---

## 🔒 Segurança pós-deploy

Após confirmar que tudo está funcionando:

1. Volte para o Render
2. Vá em **"Environment"**
3. **Remova** a variável `ADMIN_PASSWORD`
4. Clique em **"Save"**

Isso evita que alguém com acesso ao painel do Render consiga trocar sua senha.

---

## 💰 Custos

| Serviço | Custo | Notas |
|---------|-------|-------|
| Render (Starter) | US$ 7/mês | Não dorme, suporta 50+ clientes |
| Disco (1 GB) | US$ 0.25/mês | Para banco SQLite |
| **Total** | **~US$ 7.25/mês** | Pagamento por cartão |

---

## 🆘 Troubleshooting

### "Erro 502 Bad Gateway"
- Espere 2 minutos (app pode estar reiniciando)
- Verifique os logs no Render (clique em "Logs")

### "Webhook retorna 401"
- Verifique se o `EDUZZ_WEBHOOK_SECRET` está correto
- Espere 1 minuto após salvar no Render (leva tempo para atualizar)

### "Não consigo logar"
- Verifique se fez a compra de teste
- Confirme que usou o mesmo email
- Verifique no painel admin se o usuário aparece com status `active`

### "Esqueci a senha de admin"
- Entre no painel do Render
- Vá em "Environment"
- Defina `ADMIN_PASSWORD` com uma nova senha
- Salve (app reinicia)
- Acesse `/admin` com a nova senha
- Remova `ADMIN_PASSWORD` das variáveis de novo

---

## 📞 Próximos passos

- [ ] Domínio próprio (opcional): Adicione em Render → "Custom Domains"
- [ ] Backup automático: Configure cron para copiar `app.db` para S3/Google Drive
- [ ] Email transacional: Integre Resend ou Brevo para recuperação de senha automática

---

**Pronto para deploy?** Comece pelo Passo 1! 🚀
