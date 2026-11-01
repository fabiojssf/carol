def test_listagem_usuarios_admin(admin_client):
    res = admin_client.get("/api/usuarios")
    assert res.status_code == 200
    usuarios = res.json()
    assert len(usuarios) >= 1
    assert usuarios[0]["email"] == "admin@carol.com"


def test_operador_bloqueado_area_administrativa(operador_client):
    res = operador_client.get("/api/usuarios")
    assert res.status_code == 403
    assert "Acesso restrito a administradores" in res.json()["detail"]


def test_crud_completo_usuario(admin_client):
    # 1. Cadastra novo usuário
    novo_payload = {
        "nome": "Carlos Analista",
        "email": "carlos@carol.com",
        "senha": "senhaSegura123",
        "perfil": "operador",
        "ativo": True
    }
    res_criar = admin_client.post("/api/usuarios", json=novo_payload)
    assert res_criar.status_code == 200
    usuario_id = res_criar.json()["id"]

    # 2. Atualiza dados
    update_payload = {
        "nome": "Carlos Analista Senior",
        "email": "carlos.senior@carol.com",
        "perfil": "operador",
        "ativo": True,
        "nova_senha": None
    }
    res_up = admin_client.put(f"/api/usuarios/{usuario_id}", json=update_payload)
    assert res_up.status_code == 200

    # 3. Verifica lista
    res_list = admin_client.get("/api/usuarios")
    nomes = [u["nome"] for u in res_list.json()]
    assert "Carlos Analista Senior" in nomes

    # 4. Remove usuário
    res_del = admin_client.delete(f"/api/usuarios/{usuario_id}")
    assert res_del.status_code == 200


def test_proibir_exclusao_proprio_admin(admin_client):
    res_me = admin_client.get("/api/auth/me")
    meu_id = res_me.json()["id"]

    res_del = admin_client.delete(f"/api/usuarios/{meu_id}")
    assert res_del.status_code == 400
    assert "não pode excluir sua própria conta" in res_del.json()["detail"]


def test_resetar_2fa_usuario(admin_client, test_storage):
    # Cria usuário com 2FA ativo
    uid = test_storage.cadastrar_usuario("Teste 2FA", "teste2fa@carol.com", "senha123", "operador")
    test_storage.salvar_totp_secret_pendente(uid, "SECRETTESTE")
    test_storage.ativar_totp(uid)

    usuario = test_storage.obter_usuario_por_id(uid)
    assert usuario["totp_habilitado"] == 1

    # Admin reseta o 2FA
    res_reset = admin_client.post(f"/api/usuarios/{uid}/resetar-2fa")
    assert res_reset.status_code == 200

    usuario_pos = test_storage.obter_usuario_por_id(uid)
    assert usuario_pos["totp_habilitado"] == 0
    assert usuario_pos["totp_secret"] is None
