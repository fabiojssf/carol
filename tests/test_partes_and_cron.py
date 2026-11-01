from datetime import datetime
from croniter import croniter


def test_crud_parte_monitorada(admin_client):
    payload = {
        "nome_parte": "BANCO SANTANDER BRASIL S.A.",
        "webhook_url": "https://meu-webhook.com/eventos",
        "cron_expression": "0 */4 * * *",
        "sigla_tribunal": "TJSP",
        "ativo": True,
        "data_inicio": "2025-01-15"
    }
    # 1. Criação com data_inicio personalizada
    res_criar = admin_client.post("/api/partes", json=payload)
    assert res_criar.status_code == 200
    parte_id = res_criar.json()["id"]

    # 2. Obtenção
    res_get = admin_client.get(f"/api/partes/{parte_id}")
    assert res_get.status_code == 200
    parte = res_get.json()
    assert parte["nome_parte"] == "BANCO SANTANDER BRASIL S.A."
    assert parte["cron_expression"] == "0 */4 * * *"
    assert parte["data_inicio"] == "2025-01-15"
    assert parte["proxima_consulta"] is not None

    # 3. Atualização
    update_payload = {
        "nome_parte": "BANCO SANTANDER (BRASIL) S.A.",
        "webhook_url": "https://meu-webhook.com/eventos-v2",
        "cron_expression": "0 8,17 * * *",
        "sigla_tribunal": None,
        "ativo": True,
        "data_inicio": "2024-06-01"
    }
    res_up = admin_client.put(f"/api/partes/{parte_id}", json=update_payload)
    assert res_up.status_code == 200

    # 4. Listagem
    res_list = admin_client.get("/api/partes")
    assert res_list.status_code == 200
    item = next(p for p in res_list.json() if p["id"] == parte_id)
    assert item["data_inicio"] == "2024-06-01"

    # 5. Exclusão
    res_del = admin_client.delete(f"/api/partes/{parte_id}")
    assert res_del.status_code == 200


def test_calculo_proxima_execucao_cron(test_storage):
    base = datetime(2026, 11, 1, 10, 0, 0)

    # A cada 2 horas (0 */2 * * *) a partir das 10:00 -> deve ser 12:00
    prox_2h = test_storage.calcular_proxima_execucao("0 */2 * * *", base_time=base)
    assert prox_2h == "2026-11-01 12:00:00"

    # Diário às 17:00
    prox_17h = test_storage.calcular_proxima_execucao("0 17 * * *", base_time=base)
    assert prox_17h == "2026-11-01 17:00:00"

    # Expressão inválida deve ter fallback seguro sem quebrar
    prox_fallback = test_storage.calcular_proxima_execucao("expressao_invalida", base_time=base)
    assert prox_fallback is not None


def test_endpoint_config_e_proxy_reverso(client):
    # Sem headers de proxy
    res = client.get("/api/config")
    assert res.status_code == 200
    dados = res.json()
    assert "base_url" in dados
    assert "banco_tipo" in dados

    # Com headers de proxy reverso simulando Nginx/Cloudflare
    res_proxy = client.get("/api/config", headers={
        "X-Forwarded-Proto": "https",
        "X-Forwarded-Host": "carol.empresa.com.br"
    })
    assert res_proxy.status_code == 200


def test_monitor_com_data_inicio_customizada(test_storage, monkeypatch):
    from monitor import CarolMonitor
    from client import ComunicaPJeClient
    from datetime import date

    chamada_cliente = {}

    def mock_iter(self, **kwargs):
        chamada_cliente.update(kwargs)
        return []

    monkeypatch.setattr(ComunicaPJeClient, "iter_todas_comunicacoes", mock_iter)

    pid = test_storage.cadastrar_parte(
        nome_parte="EMPRESA TESTE DATAS",
        webhook_url="https://webhook.site/teste",
        data_inicio="2025-03-01"
    )
    parte = test_storage.obter_parte(pid)

    motor = CarolMonitor(storage=test_storage)
    motor.executar_varredura_parte(parte)

    hoje = date.today().strftime("%Y-%m-%d")
    assert chamada_cliente["data_inicio"] == "2025-03-01"
    assert chamada_cliente["data_fim"] == hoje
