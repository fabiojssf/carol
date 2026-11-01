from models import Comunicacao, Destinatario, DestinatarioAdvogado, Advogado
from notifier import CarolNotifier


def criar_comunicacao_fake(id_com: int, numero_proc: str, hash_val: str, status: str = "P") -> Comunicacao:
    return Comunicacao(
        id=id_com,
        data_disponibilizacao="2026-10-30",
        siglaTribunal="TJSP",
        tipoComunicacao="Intimação",
        nomeOrgao="1ª Vara Cível",
        numero_processo=numero_proc,
        numeroprocessocommascara="1000000-00.2026.8.26.0100",
        hash=hash_val,
        status=status,
        texto="<p>Vistos. Intime-se a parte requerente.</p>"
    )


def test_motor_de_diff_snapshots(test_storage):
    # 1. Cadastra uma parte
    pid = test_storage.cadastrar_parte("EMPRESA TESTE S.A.", "https://webhook.site/teste")

    com1 = criar_comunicacao_fake(101, "0001", "hash_aaa", "P")
    com2 = criar_comunicacao_fake(102, "0002", "hash_bbb", "P")

    # 1ª Varredura: Ambas são inéditas
    novas_1 = test_storage.identificar_novas_ou_atualizadas(pid, [com1, com2])
    assert len(novas_1) == 2
    assert {c.id for c in novas_1} == {101, 102}

    # 2ª Varredura: Mesmos dados retornados -> ZERO novidades (Diff estrito)
    novas_2 = test_storage.identificar_novas_ou_atualizadas(pid, [com1, com2])
    assert len(novas_2) == 0

    # 3ª Varredura: com1 teve o status alterado para "C" (Concluído)
    com1_modificada = criar_comunicacao_fake(101, "0001", "hash_aaa", "C")
    novas_3 = test_storage.identificar_novas_ou_atualizadas(pid, [com1_modificada, com2])
    assert len(novas_3) == 1
    assert novas_3[0].id == 101

    # 4ª Varredura: com3 nova adicionada
    com3 = criar_comunicacao_fake(103, "0003", "hash_ccc", "P")
    novas_4 = test_storage.identificar_novas_ou_atualizadas(pid, [com1_modificada, com2, com3])
    assert len(novas_4) == 1
    assert novas_4[0].id == 103


def test_formatacao_payload_webhook_com_base_url(test_storage, monkeypatch):
    base_url_custom = "https://carol.meudominio.com.br"
    notifier = CarolNotifier(storage=test_storage, base_url=base_url_custom)

    pid = test_storage.cadastrar_parte("BANCO BRADESCO S.A.", "https://meu-webhook.com/api", sigla_tribunal="TJSP")
    parte = test_storage.obter_parte(pid)

    com = criar_comunicacao_fake(555, "00012348820268260100", "hash_certidao_123")

    # Intercepta a chamada HTTP do requests para validar o payload
    chamada_registrada = {}

    def mock_post(url, json=None, headers=None, timeout=None):
        chamada_registrada["url"] = url
        chamada_registrada["json"] = json
        class MockResp:
            status_code = 200
            text = '{"success": true}'
        return MockResp()

    import requests
    monkeypatch.setattr(requests, "post", mock_post)

    resultados = notifier.enviar_evento_webhook(
        parte=parte,
        comunicacoes_modificadas=[com],
        baixar_pdf=False
    )

    assert len(resultados) == 1
    assert resultados[0]["status_code"] == 200

    # Validações do Payload
    payload = chamada_registrada["json"]
    assert payload["evento"] == "ATUALIZACAO_PROCESSUAL"
    assert payload["base_url"] == base_url_custom
    assert payload["parte_monitorada"]["nome"] == "BANCO BRADESCO S.A."
    
    # Links utilizando a BASE_URL pública
    com_dict = payload["comunicacao"]
    assert com_dict["link_certidao_carol"] == f"{base_url_custom}/api/comunicacoes/hash_certidao_123/certidao"
    assert com_dict["link_painel_carol"] == f"{base_url_custom}/"
    assert "localhost" not in com_dict["link_certidao_carol"]

    # Histórico registrado no banco
    historico = test_storage.listar_historico_webhooks()
    assert len(historico) == 1
    assert historico[0]["status_code"] == 200
