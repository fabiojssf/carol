import os
import json
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path
from datetime import datetime
import requests

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from models import Comunicacao
from storage import CarolStorage
import config

logger = logging.getLogger("carol.notifier")


class CarolNotifier:
    """Disparador de eventos Webhook e notificações visuais com suporte a BASE_URL configurável."""

    def __init__(
        self,
        storage: Optional[CarolStorage] = None,
        pasta_certidoes: Optional[str] = None,
        base_url: Optional[str] = None,
        console: Optional[Console] = None
    ):
        self.storage = storage or CarolStorage()
        self.pasta_certidoes = Path(pasta_certidoes or config.CERTIDOES_DIR)
        self.pasta_certidoes.mkdir(parents=True, exist_ok=True)
        self.base_url = (base_url or config.BASE_URL).rstrip("/")
        self.console = console or Console()

    def enviar_evento_webhook(
        self,
        parte: Dict[str, Any],
        comunicacoes_modificadas: List[Comunicacao],
        client=None,
        baixar_pdf: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Envia o evento para a URL de Webhook específica da Parte.
        O payload segue o formato JSON Estruturado Completo utilizando a BASE_URL pública do sistema.
        """
        webhook_url = parte.get("webhook_url")
        parte_id = parte["id"]
        nome_parte = parte["nome_parte"]

        resultados = []

        for c in comunicacoes_modificadas:
            proc = c.numeroprocessocommascara or c.numero_processo or "SEM_NUMERO"

            # 1. Download do PDF se aplicável
            caminho_pdf_relativo = None
            if baixar_pdf and c.hash and client:
                try:
                    nome_pdf = f"{c.numero_processo or 'proc'}_{c.id}.pdf"
                    caminho_pdf = self.pasta_certidoes / nome_pdf
                    client.baixar_certidao(c.hash, salvar_em=str(caminho_pdf))
                    caminho_pdf_relativo = str(caminho_pdf)
                except Exception as e:
                    logger.warning("Falha ao baixar certidão PDF para comunicação %s: %s", c.id, e)

            # 2. Links públicos formatados com a BASE_URL configurada no .env
            link_certidao_carol = f"{self.base_url}/api/comunicacoes/{c.hash}/certidao" if c.hash else None
            link_painel_carol = f"{self.base_url}/"

            # 3. Payload Estruturado Completo
            payload = {
                "evento": "ATUALIZACAO_PROCESSUAL",
                "timestamp": datetime.now().isoformat(),
                "base_url": self.base_url,
                "parte_monitorada": {
                    "id": parte_id,
                    "nome": nome_parte,
                    "tribunal_filtro": parte.get("sigla_tribunal")
                },
                "comunicacao": {
                    "id": c.id,
                    "numero_processo": c.numero_processo,
                    "numero_processo_mascara": c.numeroprocessocommascara,
                    "sigla_tribunal": c.siglaTribunal,
                    "nome_orgao": c.nomeOrgao,
                    "tipo_comunicacao": c.tipoComunicacao,
                    "tipo_documento": c.tipoDocumento,
                    "nome_classe": c.nomeClasse,
                    "data_disponibilizacao": c.data_disponibilizacao,
                    "meio": c.meiocompleto or c.meio,
                    "texto_resumo": c.texto_limpo,
                    "link_autos": c.link,
                    "hash_certidao": c.hash,
                    "link_certidao_api": f"https://comunicaapi.pje.jus.br/api/v1/comunicacao/{c.hash}/certidao" if c.hash else None,
                    "link_certidao_carol": link_certidao_carol,
                    "link_painel_carol": link_painel_carol,
                    "arquivo_certidao_local": caminho_pdf_relativo,
                    "destinatarios": [d.model_dump() for d in c.destinatarios],
                    "advogados": [
                        {
                            "nome": da.advogado.nome if da.advogado else None,
                            "numero_oab": da.advogado.numero_oab if da.advogado else None,
                            "uf_oab": da.advogado.uf_oab if da.advogado else None
                        }
                        for da in c.destinatarioadvogados if da.advogado
                    ]
                }
            }

            # 4. Disparo HTTP POST
            status_code = 0
            sucesso = False
            resposta_texto = ""

            if webhook_url:
                try:
                    resp = requests.post(
                        webhook_url,
                        json=payload,
                        headers={"Content-Type": "application/json", "User-Agent": "CAROL-NotificationEngine/1.0"},
                        timeout=15
                    )
                    status_code = resp.status_code
                    sucesso = 200 <= status_code < 300
                    resposta_texto = resp.text[:1000]
                except Exception as e:
                    resposta_texto = str(e)
                    logger.error("Erro ao enviar webhook para %s: %s", webhook_url, e)

            # 5. Registra no Histórico
            self.storage.registrar_webhook_disparado(
                parte_id=parte_id,
                comunicacao_id=c.id,
                numero_processo=proc,
                webhook_url=webhook_url or "NAO_CONFIGURADO",
                status_code=status_code,
                sucesso=sucesso,
                payload=payload,
                resposta_texto=resposta_texto
            )

            # 6. Notificação Visual no Console
            self._notificar_console(c, nome_parte=nome_parte, webhook_status=status_code)

            resultados.append({
                "comunicacao_id": c.id,
                "processo": proc,
                "webhook_url": webhook_url,
                "status_code": status_code,
                "sucesso": sucesso
            })

        if resultados:
            self.storage.incrementar_notificacoes_parte(parte_id, len(resultados))

        return resultados

    def _notificar_console(self, c: Comunicacao, nome_parte: Optional[str] = None, webhook_status: int = 0):
        proc = c.numeroprocessocommascara or c.numero_processo or "NÃO INFORMADO"
        tribunal = c.siglaTribunal or "N/A"
        tipo = c.tipoComunicacao or "Comunicação"
        data = c.data_disponibilizacao or "Hoje"

        corpo = Text()
        if nome_parte:
            corpo.append("Parte Monitorada: ", style="bold yellow")
            corpo.append(f"{nome_parte}\n", style="white")

        corpo.append("Processo: ", style="bold cyan")
        corpo.append(f"{proc}\n", style="white")

        corpo.append("Tribunal / Órgão: ", style="bold cyan")
        corpo.append(f"[{tribunal}] {c.nomeOrgao or 'Judiciário'}\n", style="white")

        corpo.append("Ato / Data: ", style="bold cyan")
        corpo.append(f"{tipo} em {data}\n", style="magenta")

        corpo.append("Webhook Disparo: ", style="bold cyan")
        if 200 <= webhook_status < 300:
            corpo.append(f"Enviado com Sucesso (HTTP {webhook_status})\n", style="bold green")
        elif webhook_status == 0:
            corpo.append("Sem Webhook / Erro de Rede\n", style="bold red")
        else:
            corpo.append(f"Retornou Erro (HTTP {webhook_status})\n", style="bold red")

        texto_preview = c.texto_limpo
        if len(texto_preview) > 240:
            texto_preview = texto_preview[:240] + "..."

        corpo.append("\nResumo do Teor:\n", style="bold underline")
        corpo.append(f"{texto_preview}\n", style="italic")

        painel = Panel(
            corpo,
            title="[bold green]🚨 EVENTO ENVIADO AO WEBHOOK[/bold green]",
            border_style="green" if 200 <= webhook_status < 300 else "yellow",
            padding=(1, 2)
        )
        self.console.print(painel)
