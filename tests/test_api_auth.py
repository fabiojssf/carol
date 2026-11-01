import pyotp


def test_endpoint_protegido_sem_autenticacao(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401
    assert "Não autenticado" in res.json()["detail"]


def test_setup_status_e_setup_inicial_primeiro_admin(client, test_storage):
    # 1. Verifica se o sistema vazio detecta a necessidade de setup
    res_status = client.get("/api/auth/setup-status")
    assert res_status.status_code == 200
    assert res_status.json()["setup_necessario"] is True
    assert res_status.json()["total_usuarios"] == 0

    # 2. Executa o primeiro cadastro de Administrador
    setup_payload = {
        "nome": "Super Administrador",
        "email": "superadmin@carol.com",
        "senha": "superSenha123"
    }
    res_setup = client.post("/api/auth/setup-inicial", json=setup_payload)
    assert res_setup.status_code == 200
    dados = res_setup.json()
    assert dados["usuario"]["email"] == "superadmin@carol.com"
    assert dados["usuario"]["perfil"] == "admin"
    assert "carol_session" in client.cookies

    # 3. Com a sessão gerada no setup, o usuário já acessa a API
    res_me = client.get("/api/auth/me")
    assert res_me.status_code == 200
    assert res_me.json()["email"] == "superadmin@carol.com"

    # 4. Agora o setup deve estar bloqueado
    res_status2 = client.get("/api/auth/setup-status")
    assert res_status2.json()["setup_necessario"] is False

    res_setup2 = client.post("/api/auth/setup-inicial", json=setup_payload)
    assert res_setup2.status_code == 400
    assert "já foi realizada" in res_setup2.json()["detail"]


def test_login_sucesso_sem_2fa(client, test_storage):
    if not test_storage.obter_usuario_por_email("admin@carol.com"):
        test_storage.cadastrar_usuario("Administrador", "admin@carol.com", "admin123", "admin", True)

    res = client.post("/api/auth/login", json={"email": "admin@carol.com", "senha": "admin123"})
    assert res.status_code == 200
    dados = res.json()
    assert dados["status"] == "sucesso"
    assert dados["usuario"]["email"] == "admin@carol.com"
    assert "carol_session" in client.cookies

    # Acessa endpoint protegido com a sessão criada
    me_res = client.get("/api/auth/me")
    assert me_res.status_code == 200
    assert me_res.json()["perfil"] == "admin"


def test_login_senha_incorreta(client, test_storage):
    if not test_storage.obter_usuario_por_email("admin@carol.com"):
        test_storage.cadastrar_usuario("Administrador", "admin@carol.com", "admin123", "admin", True)

    res = client.post("/api/auth/login", json={"email": "admin@carol.com", "senha": "senha_errada"})
    assert res.status_code == 401
    assert "Email ou senha incorretos" in res.json()["detail"]


def test_fluxo_completo_ativacao_e_login_2fa(admin_client, test_storage):
    # 1. Gera segredo e QR code
    res_gerar = admin_client.post("/api/auth/2fa/gerar")
    assert res_gerar.status_code == 200
    dados_2fa = res_gerar.json()
    secret = dados_2fa["secret"]
    assert len(secret) == 32
    assert "qrcode_base64" in dados_2fa

    # 2. Gera código válido no autenticador virtual
    totp = pyotp.TOTP(secret)
    codigo_valido = totp.now()

    # 3. Confirma ativação
    res_confirma = admin_client.post("/api/auth/2fa/confirmar", json={"codigo_2fa": codigo_valido})
    assert res_confirma.status_code == 200
    assert "ativada com sucesso" in res_confirma.json()["mensagem"]

    # 4. Desconecta
    admin_client.post("/api/auth/logout")

    # 5. Tenta login: deve exigir 2FA
    res_login = admin_client.post("/api/auth/login", json={"email": "admin@carol.com", "senha": "admin123"})
    assert res_login.status_code == 200
    dados_login = res_login.json()
    assert dados_login["status"] == "2fa_obrigatorio"
    temp_token = dados_login["temp_token"]

    # 6. Finaliza login com código 2FA
    codigo_atual = totp.now()
    res_2fa = admin_client.post("/api/auth/login-2fa", json={
        "temp_token": temp_token,
        "codigo_2fa": codigo_atual
    })
    assert res_2fa.status_code == 200
    assert res_2fa.json()["status"] == "sucesso"
    assert "carol_session" in admin_client.cookies


def test_logout(admin_client):
    res_me = admin_client.get("/api/auth/me")
    assert res_me.status_code == 200

    res_logout = admin_client.post("/api/auth/logout")
    assert res_logout.status_code == 200

    # Após logout, deve retornar 401
    res_pos = admin_client.get("/api/auth/me")
    assert res_pos.status_code == 401
