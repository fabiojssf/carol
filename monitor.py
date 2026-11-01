import time
import logging
from typing import Optional, List, Dict, Any
from datetime import date, datetime, timedelta
from rich.console import Console

from client import ComunicaPJeClient
from storage import CarolStorage
from notifier import CarolNotifier

logger = logging.getLogger("carol.monitor")


class CarolMonitor:
    """Motor de monitoramento inteligente para Partes Processuais."""

    def __init__(
        self,
        client: Optional[ComunicaPJeClient] = None,
        storage: Optional[CarolStorage] = None,
        notifier: Optional[CarolNotifier] = None,
        console: Optional[Console] = None
    ):
        self.console = console or Console()
        self.client = client or ComunicaPJeClient()
        self.storage = storage or CarolStorage()
        self.notifier = notifier or CarolNotifier(storage=self.storage, console=self.console)

    def executar_varredura_parte(
        self,
        parte: Dict[str, Any],
        dias_retroativos: int = 30,
        baixar_certidoes: bool = True
    ) -> int:
        """
        Executa a consulta na API do Comunica PJe para uma parte específica no intervalo de 30 dias.
        Compara com o snapshot anterior e SÓ dispara webhook se houver nova comunicação ou atualização.
        """
        parte_id = parte["id"]
        nome_parte = parte["nome_parte"]
        sigla_tribunal = parte.get("sigla_tribunal")
        cron_expr = parte.get("cron_expression", "0 */2 * * *")

        hoje = date.today()
        data_fim = hoje.strftime("%Y-%m-%d")

        if parte.get("data_inicio") and str(parte["data_inicio"]).strip():
            data_inicio = str(parte["data_inicio"]).strip()
            periodo_desc = f"Desde {data_inicio} até Hoje ({data_fim})"
        elif dias_retroativos and dias_retroativos > 0:
            data_inicio = (hoje - timedelta(days=dias_retroativos)).strftime("%Y-%m-%d")
            periodo_desc = f"Últimos {dias_retroativos} dias ({data_inicio} até {data_fim})"
        else:
            data_inicio = None
            periodo_desc = f"Histórico Completo até Hoje ({data_fim})"

        self.console.print(f"[cyan]Consultando parte:[/cyan] [bold white]'{nome_parte}'[/bold white] [dim]({periodo_desc})[/dim]")

        try:
            # 1. Busca todas as comunicações da parte no período
            comunicacoes_encontradas = list(
                self.client.iter_todas_comunicacoes(
                    nome_parte=nome_parte,
                    sigla_tribunal=sigla_tribunal,
                    data_inicio=data_inicio,
                    data_fim=data_fim,
                    itens_por_pagina=100
                )
            )

            # 2. Identifica apenas as novidades ou atualizações comparando com o snapshot anterior
            modificadas = self.storage.identificar_novas_ou_atualizadas(
                parte_id=parte_id,
                comunicacoes_atuais=comunicacoes_encontradas
            )

            # 3. Se houver novidades, dispara os Webhooks configurados
            if modificadas:
                self.console.print(f"[bold yellow]Detectadas {len(modificadas)} atualização(ões) para '{nome_parte}'! Disparando Webhook...[/bold yellow]")
                self.notifier.enviar_evento_webhook(
                    parte=parte,
                    comunicacoes_modificadas=modificadas,
                    client=self.client,
                    baixar_pdf=baixar_certidoes
                )
            else:
                self.console.print(f"[dim green]Nenhuma alteração detectada para '{nome_parte}'. Nenhum webhook necessário.[/dim green]")

            # 4. Atualiza os horários de execução
            self.storage.atualizar_execucao_parte(parte_id, cron_expr)
            return len(modificadas)

        except Exception as e:
            self.console.print(f"[red]Erro ao processar parte '{nome_parte}': {e}[/red]")
            logger.exception("Falha na varredura da parte %s: %s", nome_parte, e)
            self.storage.atualizar_execucao_parte(parte_id, cron_expr)
            return 0

    def executar_todas_as_partes(self, dias_retroativos: int = 30) -> int:
        """Executa a verificação em todas as partes ativas."""
        partes = [p for p in self.storage.listar_partes() if p["ativo"]]
        if not partes:
            return 0

        total_modificadas = 0
        for p in partes:
            total_modificadas += self.executar_varredura_parte(p, dias_retroativos=dias_retroativos)
        return total_modificadas

    def verificar_e_executar_agendadas(self, dias_retroativos: int = 30) -> int:
        """
        Verifica quais partes atingiram o horário de agendamento do seu cron e as executa.
        """
        agora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        partes = [p for p in self.storage.listar_partes() if p["ativo"]]

        total_executadas = 0
        for p in partes:
            proxima = p.get("proxima_consulta")
            if not proxima or proxima <= agora_str:
                self.executar_varredura_parte(p, dias_retroativos=dias_retroativos)
                total_executadas += 1

        return total_executadas
