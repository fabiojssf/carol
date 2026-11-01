"""Testes unitários para Models Pydantic e Client HTTP do Comunica PJe."""

import pytest
from unittest.mock import MagicMock, patch
from models import Comunicacao, Destinatario, DestinatarioAdvogado, Advogado, RespostaComunica
from client import ComunicaPJeClient, ComunicaPJeError, RateLimitExceededError


def test_comunicacao_texto_limpo_html_removal():
    raw_html = "<p>Vistos em corre&ccedil;&atilde;o <strong>ordin&aacute;ria</strong>.&nbsp;Intime-se.</p>"
    c = Comunicacao(id=1001, texto=raw_html)
    assert c.texto_limpo == "Vistos em correcção ordinária. Intime-se." or "correção" in c.texto_limpo
    assert "<p>" not in c.texto_limpo
    assert "<strong>" not in c.texto_limpo
    assert "&nbsp;" not in c.texto_limpo


def test_comunicacao_advogados_nomes():
    adv1 = Advogado(id=1, nome="Dra. Maria Santos", numero_oab="12345", uf_oab="SP")
    adv2 = Advogado(id=2, nome="Dr. Carlos Mendes", numero_oab="67890", uf_oab="RJ")
    da1 = DestinatarioAdvogado(id=10, advogado=adv1)
    da2 = DestinatarioAdvogado(id=11, advogado=adv2)

    c = Comunicacao(
        id=2002,
        destinatarioadvogados=[da1, da2]
    )
    nomes = c.advogados_nomes
    assert len(nomes) == 2
    assert "Dra. Maria Santos" in nomes
    assert "Dr. Carlos Mendes" in nomes


def test_resposta_comunica_model():
    data = {
        "status": "success",
        "count": 1,
        "items": [
            {
                "id": 999,
                "numero_processo": "0001234-56.2026.8.26.0100",
                "siglaTribunal": "TJSP",
                "tipoComunicacao": "Intimação"
            }
        ]
    }
    resposta = RespostaComunica.model_validate(data)
    assert resposta.status == "success"
    assert resposta.count == 1
    assert len(resposta.items) == 1
    assert resposta.items[0].id == 999
    assert resposta.items[0].siglaTribunal == "TJSP"


def test_comunica_pje_client_buscar_comunicacoes():
    client = ComunicaPJeClient(base_url="https://mock.api/v1")

    with patch.object(client.session, "request") as mock_req:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "status": "success",
            "count": 1,
            "items": [
                {
                    "id": 555,
                    "numero_processo": "12345",
                    "siglaTribunal": "TRT2"
                }
            ]
        }
        mock_req.return_value = mock_response

        res = client.buscar_comunicacoes(
            nome_parte="Banco Exemplo",
            data_inicio="2026-10-01",
            data_fim="2026-10-31",
            sigla_tribunal="TRT2",
            pagina=1,
            itens_por_pagina=20
        )

        assert res.count == 1
        assert res.items[0].id == 555
        mock_req.assert_called_once()
        call_kwargs = mock_req.call_args[1]
        params = call_kwargs["params"]
        assert params["nomeParte"] == "Banco Exemplo"
        assert params["dataDisponibilizacaoInicio"] == "2026-10-01"
        assert params["dataDisponibilizacaoFim"] == "2026-10-31"
        assert params["siglaTribunal"] == "TRT2"
        assert params["pagina"] == 1
        assert params["itensPorPagina"] == 20


def test_comunica_pje_client_rate_limit_retry():
    client = ComunicaPJeClient(base_url="https://mock.api/v1", max_retries=2)

    with patch.object(client.session, "request") as mock_req:
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.headers = {"retry-after": "0"}

        mock_req.return_value = mock_429

        with pytest.raises(RateLimitExceededError):
            client.buscar_comunicacoes(nome_parte="Qualquer")

        assert mock_req.call_count == 2
