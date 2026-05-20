#!/usr/bin/env python3
"""
Script de teste local - valida o app antes de fazer deploy
Simula compra na Eduzz, cadastro de senha e login
"""

import os
import sys
import json
import time
import subprocess
import requests
import hmac
import hashlib
from threading import Thread
from datetime import datetime

# Configuração
BASE_URL = "http://127.0.0.1:4182"
WEBHOOK_SECRET = "test_secret_123"
TEST_EMAIL = "teste@cliente.com"
TEST_PASSWORD = "Senha123456"

def setup_env():
    """Configura variáveis de ambiente para teste"""
    os.environ["HOST"] = "127.0.0.1"
    os.environ["PORT"] = "4182"
    os.environ["WEBHOOK_SECRET"] = WEBHOOK_SECRET
    os.environ["ADMIN_EMAIL"] = "admin@test.com"
    os.environ["ADMIN_PASSWORD"] = "AdminTest123"
    os.environ["DATABASE"] = "test.db"
    os.environ["DATA_DIR"] = "."
    print("✓ Variáveis de ambiente configuradas")

def start_server():
    """Inicia servidor em thread separada"""
    print("\n🚀 Iniciando servidor...")
    # Limpar banco de dados anterior
    if os.path.exists("test.db"):
        os.remove("test.db")
    
    # Iniciar app
    subprocess.Popen([sys.executable, "app.py"], 
                     stdout=subprocess.PIPE, 
                     stderr=subprocess.PIPE)
    
    # Aguardar servidor ficar pronto
    for i in range(30):
        try:
            requests.get(f"{BASE_URL}/login", timeout=1)
            print("✓ Servidor está pronto!")
            return True
        except:
            time.sleep(0.5)
    
    print("✗ Servidor não respondeu após 15 segundos")
    return False

def test_webhook():
    """Testa webhook com assinatura HMAC válida"""
    print("\n📨 Testando webhook...")
    
    # Payload de teste (simula compra na Eduzz)
    payload = {
        "id": f"event-{int(time.time())}",
        "event": "myeduzz.invoice_paid",
        "data": {
            "buyer": {
                "email": TEST_EMAIL,
                "name": "Cliente Teste",
                "id": "123"
            },
            "invoice": {
                "id": "inv-123",
                "status": "paid"
            }
        }
    }
    
    body = json.dumps(payload).encode('utf-8')
    
    # Gerar assinatura HMAC
    signature = hmac.new(
        WEBHOOK_SECRET.encode('utf-8'),
        body,
        hashlib.sha256
    ).hexdigest()
    
    # Enviar webhook
    response = requests.post(
        f"{BASE_URL}/webhook/eduzz",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Signature": signature
        }
    )
    
    if response.status_code == 200:
        print(f"✓ Webhook processado com sucesso")
        print(f"  Resposta: {response.json()}")
        return True
    else:
        print(f"✗ Webhook retornou {response.status_code}")
        print(f"  Resposta: {response.text}")
        return False

def test_register():
    """Testa cadastro de senha"""
    print("\n📝 Testando cadastro de senha...")
    
    # Acessar página de cadastro
    response = requests.get(f"{BASE_URL}/cadastrar")
    if response.status_code != 200:
        print(f"✗ Página de cadastro retornou {response.status_code}")
        return False
    
    # Enviar formulário de cadastro
    response = requests.post(
        f"{BASE_URL}/cadastrar",
        data={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
            "confirm": TEST_PASSWORD
        }
    )
    
    if response.status_code == 200 and "sucesso" in response.text.lower():
        print(f"✓ Senha cadastrada com sucesso para {TEST_EMAIL}")
        return True
    else:
        print(f"✗ Cadastro falhou")
        print(f"  Resposta: {response.text[:200]}")
        return False

def test_login():
    """Testa login"""
    print("\n🔐 Testando login...")
    
    # Fazer login
    response = requests.post(
        f"{BASE_URL}/login",
        data={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        },
        allow_redirects=False
    )
    
    if response.status_code == 302 and "/dashboard" in response.headers.get("Location", ""):
        print(f"✓ Login bem-sucedido para {TEST_EMAIL}")
        
        # Extrair session cookie
        cookies = response.cookies
        if "session" in cookies:
            print(f"✓ Session cookie criada")
            return True
        else:
            print(f"✗ Session cookie não foi criada")
            return False
    else:
        print(f"✗ Login falhou (status {response.status_code})")
        return False

def test_session_uniqueness():
    """Testa sessão única (segunda sessão invalida a primeira)"""
    print("\n🔄 Testando sessão única...")
    
    # Primeira sessão
    response1 = requests.post(
        f"{BASE_URL}/login",
        data={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        },
        allow_redirects=False
    )
    
    session1 = response1.cookies.get("session")
    
    # Segunda sessão
    response2 = requests.post(
        f"{BASE_URL}/login",
        data={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD
        },
        allow_redirects=False
    )
    
    session2 = response2.cookies.get("session")
    
    if session1 and session2 and session1 != session2:
        print(f"✓ Sessões diferentes criadas")
        
        # Testar se primeira sessão foi invalidada
        response_check = requests.get(
            f"{BASE_URL}/dashboard",
            cookies={"session": session1}
        )
        
        if response_check.status_code == 302:
            print(f"✓ Primeira sessão foi invalidada (sessão única funcionando)")
            return True
        else:
            print(f"⚠ Primeira sessão ainda é válida")
            return False
    else:
        print(f"✗ Sessões não foram criadas corretamente")
        return False

def test_admin_login():
    """Testa login no painel admin"""
    print("\n👨‍💼 Testando login admin...")
    
    response = requests.post(
        f"{BASE_URL}/admin/login",
        data={
            "email": os.environ["ADMIN_EMAIL"],
            "password": os.environ["ADMIN_PASSWORD"]
        },
        allow_redirects=False
    )
    
    if response.status_code == 302 or response.status_code == 200:
        print(f"✓ Login admin bem-sucedido")
        return True
    else:
        print(f"✗ Login admin falhou (status {response.status_code})")
        return False

def main():
    """Executa todos os testes"""
    print("=" * 60)
    print("🧪 TESTE LOCAL - Dashboard ADS ML")
    print("=" * 60)
    
    setup_env()
    
    if not start_server():
        print("\n✗ Não foi possível iniciar o servidor")
        return False
    
    time.sleep(2)  # Aguardar servidor estar completamente pronto
    
    tests = [
        ("Webhook", test_webhook),
        ("Cadastro", test_register),
        ("Login", test_login),
        ("Sessão Única", test_session_uniqueness),
        ("Admin", test_admin_login),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            print(f"✗ Erro ao executar teste: {e}")
            results[name] = False
    
    # Resumo
    print("\n" + "=" * 60)
    print("📊 RESUMO DOS TESTES")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✓" if result else "✗"
        print(f"{status} {name}")
    
    print(f"\nResultado: {passed}/{total} testes passaram")
    
    if passed == total:
        print("\n🎉 Todos os testes passaram! Seu app está pronto para deploy.")
        return True
    else:
        print(f"\n⚠️  {total - passed} teste(s) falharam. Verifique os erros acima.")
        return False

if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⏹️  Testes interrompidos pelo usuário")
        sys.exit(1)
