import sys
import argparse
from datetime import date
from rich.console import Console
from rich.table import Table

from client import ComunicaPJeClient
from storage import CarolStorage
from notifier import CarolNotifier
from monitor import CarolMonitor


def main():
    console = Console()
    parser = argparse.ArgumentParser(
        description="CAROL - Sistema Inteligente de Notificações para Movimentações de Processos (Comunica PJe / DJEN)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="comando", help="Comandos disponíveis")

    # Comando: buscar
    p_buscar = subparsers.add_parser("buscar", help="Faz uma consulta direta de comunicações na API do PJe")
    p_buscar.add_argument("--oab", help="Número da OAB")
    p_buscar.add_argument("--uf", help="UF da OAB (ex: SP, RJ)")
    p_buscar.add_argument("--processo", help="Número do processo (com ou sem máscara)")
    p_buscar.add_argument("--parte", help="Nome da parte envolvida")
    p_buscar.add_argument("--tribunal", help="Sigla do tribunal (ex: TJSP, TRT2, STJ)")
    p_buscar.add_argument("--inicio", help="Data inicial (AAAA-MM-DD)")
    p_buscar.add_argument("--fim", help="Data final (AAAA-MM-DD)")
    p_buscar.add_argument("--limite", type=int, default=10, help="Quantidade máxima de resultados a exibir")

    # Comando: adicionar-oab
    p_add_oab = subparsers.add_parser("adicionar-oab", help="Cadastra uma OAB para monitoramento contínuo")
    p_add_oab.add_argument("numero", help="Número da OAB")
    p_add_oab.add_argument("uf", help="UF da OAB")
    p_add_oab.add_argument("--nome", help="Nome do advogado ou anotação", default="")

    # Comando: adicionar-processo
    p_add_proc = subparsers.add_parser("adicionar-processo", help="Cadastra um processo para monitoramento contínuo")
    p_add_proc.add_argument("processo", help="Número do processo CNJ")
    p_add_proc.add_argument("--descricao", help="Descrição ou anotação do processo", default="")

    # Comando: listar-alvos
    subparsers.add_parser("listar-alvos", help="Lista todos os processos e OABs cadastrados para monitoramento")

    # Comando: remover-alvo
    p_rem = subparsers.add_parser("remover-alvo", help="Remove um alvo de monitoramento pelo ID")
    p_rem.add_argument("id", type=int, help="ID do alvo obtido em listar-alvos")

    # Comando: monitor
    p_mon = subparsers.add_parser("monitor", help="Inicia o serviço de monitoramento periódico de novas publicações")
    p_mon.add_argument("--intervalo", type=int, default=60, help="Intervalo em minutos entre cada checagem (padrão: 60)")
    p_mon.add_argument("--uma-vez", action="store_true", help="Executa apenas uma varredura imediatamente e encerra")
    p_mon.add_argument("--dias", type=int, default=1, help="Dias retroativos para checar (padrão: 1)")

    # Comando: certidao
    p_cert = subparsers.add_parser("certidao", help="Baixa a certidão oficial comprobatória de uma publicação em PDF")
    p_cert.add_argument("hash", help="Hash da comunicação")
    p_cert.add_argument("-o", "--output", default="certidao.pdf", help="Nome do arquivo de saída (padrão: certidao.pdf)")

    # Comando: tribunais
    subparsers.add_parser("tribunais", help="Lista todos os tribunais integrados ao sistema do CNJ")

    args = parser.parse_args()

    if not args.comando:
        parser.print_help()
        sys.exit(0)

    client = ComunicaPJeClient()
    storage = CarolStorage()
    notifier = CarolNotifier(console=console)
    motor = CarolMonitor(client=client, storage=storage, notifier=notifier, console=console)

    if args.comando == "buscar":
        console.print("[cyan]Realizando consulta na API do Comunica PJe...[/cyan]")
        resposta = client.buscar_comunicacoes(
            numero_oab=args.oab,
            uf_oab=args.uf,
            numero_processo=args.processo,
            nome_parte=args.parte,
            sigla_tribunal=args.tribunal,
            data_inicio=args.inicio,
            data_fim=args.fim,
            itens_por_pagina=args.limite
        )

        console.print(f"[bold green]Total de registros encontrados: {resposta.count}[/bold green]\n")

        if not resposta.items:
            console.print("[yellow]Nenhuma comunicação encontrada para os filtros informados.[/yellow]")
            return

        for c in resposta.items[:args.limite]:
            notifier._notificar_console(c)

    elif args.comando == "adicionar-oab":
        sucesso = storage.adicionar_alvo_oab(args.numero, args.uf, args.nome)
        if sucesso:
            console.print(f"[green]✓ OAB {args.uf.upper()} {args.numero} cadastrada com sucesso para monitoramento![/green]")
        else:
            console.print(f"[yellow]A OAB {args.uf.upper()} {args.numero} já estava cadastrada.[/yellow]")

    elif args.comando == "adicionar-processo":
        sucesso = storage.adicionar_alvo_processo(args.processo, args.descricao)
        if sucesso:
            console.print(f"[green]✓ Processo {args.processo} cadastrado com sucesso para monitoramento![/green]")
        else:
            console.print(f"[yellow]O processo {args.processo} já estava cadastrado.[/yellow]")

    elif args.comando == "listar-alvos":
        alvos = storage.listar_alvos()
        if not alvos:
            console.print("[yellow]Nenhum alvo cadastrado ainda. Use 'adicionar-oab' ou 'adicionar-processo'.[/yellow]")
            return

        tabela = Table(title="Alvos Cadastrados para Monitoramento no CAROL")
        tabela.add_column("ID", justify="right", style="cyan")
        tabela.add_column("Tipo", style="magenta")
        tabela.add_column("Identificador", style="bold green")
        tabela.add_column("UF", style="white")
        tabela.add_column("Descrição / Titular", style="yellow")
        tabela.add_column("Cadastrado em", style="dim")

        for a in alvos:
            tabela.add_row(
                str(a["id"]),
                a["tipo"],
                a["identificador"],
                a.get("uf") or "-",
                a.get("descricao") or "-",
                a["criado_em"]
            )
        console.print(tabela)

    elif args.comando == "remover-alvo":
        sucesso = storage.remover_alvo(args.id)
        if sucesso:
            console.print(f"[green]✓ Alvo {args.id} removido com sucesso.[/green]")
        else:
            console.print(f"[red]Alvo {args.id} não encontrado.[/red]")

    elif args.comando == "monitor":
        if args.uma_vez:
            motor.executar_varredura(dias_retroativos=args.dias)
        else:
            motor.iniciar_loop(intervalo_minutos=args.intervalo, dias_retroativos=args.dias)

    elif args.comando == "certidao":
        console.print(f"[cyan]Baixando certidão para o hash '{args.hash}'...[/cyan]")
        client.baixar_certidao(args.hash, salvar_em=args.output)
        console.print(f"[bold green]✓ Certidão PDF salva com sucesso em '{args.output}'[/bold green]")

    elif args.comando == "tribunais":
        console.print("[cyan]Obtendo lista de tribunais integrados ao CNJ...[/cyan]")
        estados = client.listar_tribunais()
        total_tribunais = sum(len(e.instituicoes) for e in estados)
        console.print(f"[bold green]Total de Tribunais/Instituições integradas: {total_tribunais}[/bold green]\n")

        for estado in estados:
            siglas = ", ".join([inst.sigla for inst in estado.instituicoes])
            uf_txt = estado.uf if estado.uf else "BR"
            console.print(f"[bold yellow]{uf_txt} - {estado.nomeEstado}:[/bold yellow] [white]{siglas}[/white]")


if __name__ == "__main__":
    main()
