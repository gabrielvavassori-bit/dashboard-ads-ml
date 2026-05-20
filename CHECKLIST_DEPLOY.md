# ✅ Checklist de Deploy - Dashboard ADS ML

Use este documento para acompanhar cada passo do deploy.

---

## 📋 Fase 1: Preparação Local

- [ ] Projeto extraído em `/home/ubuntu/dashboard-ads-ml`
- [ ] Git inicializado com commit inicial
- [ ] Logo atualizado em `assets/logo-un-clic.png`
- [ ] Arquivo `.env.example` revisado
- [ ] Arquivo `render.yaml` revisado

---

## 🐙 Fase 2: GitHub

### Criar repositório

- [ ] Acesso a https://github.com/new
- [ ] Repositório criado: `dashboard-ads-ml`
- [ ] Configurado como **Public**
- [ ] URL do repositório: `https://github.com/SEU_USUARIO/dashboard-ads-ml`

### Fazer push do código

```bash
cd /home/ubuntu/dashboard-ads-ml
git remote add origin https://github.com/SEU_USUARIO/dashboard-ads-ml.git
git branch -M main
git push -u origin main
```

- [ ] Código enviado para GitHub
- [ ] Arquivo `render.yaml` visível no repositório
- [ ] Arquivo `app.py` visível no repositório

---

## 🌐 Fase 3: Render.com

### Criar conta

- [ ] Acesso a https://render.com
- [ ] Conta criada (pode usar GitHub para login)
- [ ] Email verificado

### Deploy via Blueprint

- [ ] Clicado em "New +" → "Blueprint"
- [ ] Repositório `dashboard-ads-ml` selecionado
- [ ] Formulário de variáveis de ambiente apareceu

### Preencher variáveis

- [ ] `APP_PUBLIC_URL`: `https://dashboard-ads-ml.onrender.com`
- [ ] `ADMIN_EMAIL`: `gabriel@unclicmarketplace.com.br`
- [ ] `ADMIN_PASSWORD`: *(salvo em gerenciador de senhas)*
- [ ] `EDUZZ_WEBHOOK_SECRET`: *(deixar em branco por enquanto)*
- [ ] `EDUZZ_PRODUCT_IDS`: *(deixar em branco)*

### Deploy iniciado

- [ ] Clicado em "Deploy"
- [ ] Build iniciada (esperar 2-3 minutos)
- [ ] App rodando em `https://dashboard-ads-ml.onrender.com`
- [ ] Status: **Live** (verde)

### Testar acesso inicial

- [ ] Acessar `https://dashboard-ads-ml.onrender.com/login`
- [ ] Página de login carrega
- [ ] Acessar `https://dashboard-ads-ml.onrender.com/admin`
- [ ] Painel admin acessível

---

## 🔐 Fase 4: Eduzz - Chave de Acesso

### Criar chave de webhook

- [ ] Acesso a https://integrations.eduzz.com/webhook/configs
- [ ] Logado na conta Eduzz
- [ ] Aba "Chaves de acesso" aberta
- [ ] Clicado em "+ Nova chave"
- [ ] Nome definido: `dashboard-ads-ml`
- [ ] Chave copiada: `EDUZZ_WEBHOOK_SECRET`
- [ ] Chave salva em gerenciador de senhas

### Atualizar no Render

- [ ] Voltado para Render: https://render.com
- [ ] Serviço `dashboard-ads-ml` selecionado
- [ ] Menu "Environment" aberto
- [ ] `EDUZZ_WEBHOOK_SECRET` preenchido com a chave
- [ ] Clicado em "Save"
- [ ] App reiniciou (aguardar 1 minuto)

---

## 🔗 Fase 5: Eduzz - Configuração do Webhook

### Criar configuração

- [ ] Voltado para https://integrations.eduzz.com/webhook/configs
- [ ] Clicado em "+ Nova configuração"
- [ ] Nome: `dashboard-ads-ml`
- [ ] Chave de acesso: selecionada a que foi criada
- [ ] URL: `https://dashboard-ads-ml.onrender.com/webhook/eduzz`
- [ ] Eventos marcados:
  - [ ] `myeduzz.invoice_paid`
  - [ ] `myeduzz.invoice_refunded`
  - [ ] `myeduzz.invoice_canceled`
  - [ ] `myeduzz.invoice_expired`
  - [ ] `myeduzz.contract_created`
  - [ ] `myeduzz.contract_updated`

### Verificar URL

- [ ] Clicado em "Verificar URL"
- [ ] Status retornou **200 OK**
- [ ] Clicado em "Salvar"
- [ ] Clicado em "Ativar"
- [ ] Configuração está **ativa** (verde)

---

## 📧 Fase 6: Eduzz - Configurar Produto

### Editar produto

- [ ] Acesso a "Meus Produtos" na Eduzz
- [ ] Produto selecionado ou criado
- [ ] Tipo: **Assinatura mensal/anual**

### Email pós-compra

- [ ] Seção "Email pós-compra" ou "Entrega" aberta
- [ ] Texto adicionado:

```
Obrigado pela compra! Para acessar o Dashboard ADS Mercado Livre:

1. Acesse: https://dashboard-ads-ml.onrender.com/cadastrar
2. Use EXATAMENTE o mesmo email que você informou nesta compra
3. Defina sua senha de acesso
4. Pronto! Sua sessão fica ativa enquanto a assinatura estiver em dia.

Importante: a sessão é única por dispositivo. Se você logar em outro lugar, a sessão anterior cai.
```

- [ ] Produto salvo

---

## 🧪 Fase 7: Teste Completo

### Teste de compra

- [ ] Fez uma compra de teste do seu produto
- [ ] Recebeu email com instruções
- [ ] Novo usuário apareceu no painel admin (`/admin`)
- [ ] Status do usuário: **active**

### Teste de cadastro

- [ ] Acessou `https://dashboard-ads-ml.onrender.com/cadastrar`
- [ ] Email de teste preenchido
- [ ] Senha definida
- [ ] Cadastro bem-sucedido

### Teste de login

- [ ] Acessou `https://dashboard-ads-ml.onrender.com/login`
- [ ] Email e senha preenchidos
- [ ] Login bem-sucedido
- [ ] Dashboard carregou

### Teste de sessão única

- [ ] Abriu segundo navegador/aba privada
- [ ] Fez login com o mesmo email
- [ ] Primeira sessão foi invalidada (redirecionada para login)

---

## 🔒 Fase 8: Segurança Pós-Deploy

### Remover senha de admin das variáveis

- [ ] Voltado para Render
- [ ] Serviço `dashboard-ads-ml` selecionado
- [ ] Menu "Environment" aberto
- [ ] Variável `ADMIN_PASSWORD` **removida**
- [ ] Clicado em "Save"
- [ ] App reiniciou

---

## 📊 Fase 9: Monitoramento

### Configurar alertas (opcional)

- [ ] Render → "Notifications"
- [ ] Email de alertas configurado
- [ ] Alertas para "Deploy failed" ativados

### Backup do banco

- [ ] Plano de backup definido
- [ ] Considerar backup mensal para S3/Google Drive

---

## 🎉 Conclusão

- [ ] Todas as fases completadas
- [ ] App online e funcionando
- [ ] Webhook processando eventos
- [ ] Clientes conseguem se cadastrar e logar
- [ ] Painel admin acessível apenas para você

**Status**: ✅ **PRONTO PARA PRODUÇÃO**

---

## 📞 Suporte

Se algo não funcionar:

1. Verifique os logs no Render (clique em "Logs")
2. Teste localmente: `python test_local.py`
3. Verifique se o webhook está ativo na Eduzz
4. Confirme que as variáveis de ambiente estão corretas

---

**Data de deploy**: ________________
**URL do app**: ________________
**Email de admin**: ________________
**Notas**: ________________
