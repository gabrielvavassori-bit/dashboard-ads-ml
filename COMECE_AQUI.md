# 🚀 COMECE AQUI - Dashboard ADS ML Online

Bem-vindo! Seu app está **100% pronto** para deploy. Este documento é seu mapa de estradas.

---

## 📍 Onde você está agora

✅ Projeto completo em `/home/ubuntu/dashboard-ads-ml`
✅ Git inicializado e commitado
✅ Autenticação com Eduzz configurada
✅ Painel admin pronto
✅ Banco de dados SQLite preparado

---

## 🎯 O que você precisa fazer (3 passos)

### Passo 1️⃣: GitHub (5 minutos)

1. Acesse https://github.com/new
2. Crie repositório chamado `dashboard-ads-ml` (Public)
3. Copie e cole no terminal:

```bash
cd /home/ubuntu/dashboard-ads-ml
git remote add origin https://github.com/SEU_USUARIO/dashboard-ads-ml.git
git branch -M main
git push -u origin main
```

**Pronto!** Seu código está no GitHub.

---

### Passo 2️⃣: Render.com (10 minutos)

1. Acesse https://render.com (crie conta se não tiver)
2. Clique em **"New +" → "Blueprint"**
3. Selecione repositório `dashboard-ads-ml`
4. Preencha as variáveis:

| Campo | Valor |
|-------|-------|
| `APP_PUBLIC_URL` | `https://dashboard-ads-ml.onrender.com` |
| `ADMIN_EMAIL` | `gabriel@unclicmarketplace.com.br` |
| `ADMIN_PASSWORD` | Crie uma senha forte (ex: `T-d230lG4v3rmCZVDxIHMQ`) |
| `EDUZZ_WEBHOOK_SECRET` | Deixe em branco por enquanto |
| `EDUZZ_PRODUCT_IDS` | Deixe em branco |

5. Clique em **"Deploy"**
6. Aguarde 2-3 minutos

**Pronto!** Seu app está online em `https://dashboard-ads-ml.onrender.com`

---

### Passo 3️⃣: Eduzz (15 minutos)

#### 3a. Criar chave de webhook

1. Acesse https://integrations.eduzz.com/webhook/configs
2. Aba **"Chaves de acesso"** → **"+ Nova chave"**
3. Nome: `dashboard-ads-ml`
4. **Copie a chave gerada**

#### 3b. Atualizar no Render

1. Volte para Render
2. Seu serviço → **"Environment"**
3. Preencha `EDUZZ_WEBHOOK_SECRET` com a chave copiada
4. Clique em **"Save"** (app reinicia)

#### 3c. Configurar webhook na Eduzz

1. Volte para https://integrations.eduzz.com/webhook/configs
2. **"+ Nova configuração"**:
   - Nome: `dashboard-ads-ml`
   - Chave: selecione a que criou
   - URL: `https://dashboard-ads-ml.onrender.com/webhook/eduzz`
   - Eventos: marque `invoice_paid`, `invoice_canceled`, `contract_created`, `contract_updated`
3. Clique em **"Verificar URL"** (deve retornar 200)
4. Clique em **"Salvar"** e **"Ativar"**

#### 3d. Configurar email pós-compra

1. Seus produtos → selecione o produto
2. Email pós-compra, adicione:

```
Obrigado pela compra! Para acessar o Dashboard ADS:

1. Acesse: https://dashboard-ads-ml.onrender.com/cadastrar
2. Use o MESMO email desta compra
3. Defina sua senha
4. Pronto!

Importante: sessão única por dispositivo.
```

3. Salve

**Pronto!** Tudo está configurado.

---

## ✅ Teste rápido

1. Faça uma **compra de teste** do seu produto
2. Verifique se recebeu o email com instruções
3. Acesse o painel admin: `https://dashboard-ads-ml.onrender.com/admin`
   - Email: `gabriel@unclicmarketplace.com.br`
   - Senha: *(a que você definiu no Passo 2)*
4. Veja o novo cliente aparecer com status **active**
5. Acesse `/cadastrar` e faça login com o email de teste

---

## 📚 Documentação completa

| Arquivo | Para quê |
|---------|----------|
| `DEPLOY_GUIA.md` | Guia passo-a-passo detalhado |
| `CHECKLIST_DEPLOY.md` | Checklist para acompanhar |
| `README.md` | Documentação técnica completa |
| `test_local.py` | Testar localmente antes de subir |

---

## 🔐 Credenciais importantes

**Salve em um gerenciador de senhas:**

- **Admin Email**: `gabriel@unclicmarketplace.com.br`
- **Admin Password**: *(a que você criou)*
- **Eduzz Webhook Secret**: *(a que você criou)*
- **App URL**: `https://dashboard-ads-ml.onrender.com`

---

## 💰 Custos

- **Render Starter**: US$ 7/mês (não dorme, suporta 50+ clientes)
- **Disco**: US$ 0.25/mês
- **Total**: ~US$ 7.25/mês

---

## 🆘 Algo deu errado?

### "Erro 502"
Espere 2 minutos e recarregue. Se persistir, verifique os logs no Render.

### "Webhook retorna 401"
Verifique se o `EDUZZ_WEBHOOK_SECRET` está correto. Espere 1 minuto após salvar.

### "Não consigo logar"
Verifique no painel admin se o usuário existe e tem status `active`.

### "Esqueci a senha de admin"
No Render, defina `ADMIN_PASSWORD` novamente, salve, e acesse `/admin` com a nova senha.

---

## 📞 Próximos passos (opcional)

- Domínio próprio: Adicione em Render → "Custom Domains"
- Backup automático: Configure cron para copiar `app.db` para S3
- Email automático: Integre Resend para recuperação de senha

---

## 🎉 Pronto?

**Comece pelo Passo 1!** Você terá tudo online em menos de 30 minutos.

Qualquer dúvida, consulte `DEPLOY_GUIA.md` ou `README.md`.

---

**Sucesso no deploy! 🚀**
