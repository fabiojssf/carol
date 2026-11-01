import time
import logging
from typing import Optional, Dict, Any, Generator, List
from pathlib import Path
import requests

from models import RespostaComunica, Comunicacao, TribunalEstado

logger = logging.getLogger("carol.client")


class ComunicaPJeError(Exception):
    """Exceção base para erros na API do Comunica PJe."""
    pass


class RateLimitExceededError(ComunicaPJeError):
    """Exceção para limite de requisições excedido (429)."""
    pass


class ComunicaPJeClient:
    """Cliente HTTP robusto para a API pública do Comunica PJe / DJEN."""

    BASE_URL = "https://comunicaapi.pje.jus.br/api/v1"

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: int = 30,
        max_retries: int = 3,
        user_agent: str = "CAROL-SistemaNotificacoes/1.0"
    ):
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Accept-Language": "pt-BR,pt;q=0.9",
        })

    def _request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        kwargs.setdefault("timeout", self.timeout)

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.request(method, url, **kwargs)

                # Verifica Rate Limiting
                remaining = response.headers.get("x-ratelimit-remaining")
                if remaining is not None and int(remaining) <= 2:
                    logger.warning("Limite de requisições quase atingido (restam %s)", remaining)
                    time.sleep(1.0)

                if response.status_code == 429:
                    wait_time = int(response.headers.get("retry-after", 5 * attempt))
                    logger.warning("Status 429 (Too Many Requests). Aguardando %ss...", wait_time)
                    if attempt == self.max_retries:
                        raise RateLimitExceededError(f"Limite excedido após {self.max_retries} tentativas.")
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()
                return response

            except requests.RequestException as e:
                logger.error("Erro na requisição para %s (tentativa %d/%d): %s", url, attempt, self.max_retries, e)
                if attempt == self.max_retries:
                    raise ComunicaPJeError(f"Falha na comunicação com API PJe: {e}") from e
                time.sleep(2 * attempt)

        raise ComunicaPJeError(f"Falha desconhecida ao requisitar {url}")

    def buscar_comunicacoes(
        self,
        numero_oab: Optional[str] = None,
        uf_oab: Optional[str] = None,
        numero_processo: Optional[str] = None,
        nome_parte: Optional[str] = None,
        sigla_tribunal: Optional[str] = None,
        data_inicio: Optional[str] = None,
        data_fim: Optional[str] = None,
        pagina: int = 1,
        itens_por_pagina: int = 50
    ) -> RespostaComunica:
        """
        Consulta as comunicações processuais (intimações, citações, editais, atas).

        :param numero_oab: Número da inscrição OAB (sem formatação ou zeros à esquerda desnecessários)
        :param uf_oab: Sigla do estado da OAB (ex: 'SP', 'RJ', 'PR')
        :param numero_processo: Número único CNJ (com ou sem máscara)
        :param nome_parte: Nome de uma das partes
        :param sigla_tribunal: Sigla do tribunal (ex: 'TJSP', 'TRT2', 'STJ')
        :param data_inicio: Data inicial da publicação (YYYY-MM-DD)
        :param data_fim: Data final da publicação (YYYY-MM-DD)
        :param pagina: Número da página (inicia em 1)
        :param itens_por_pagina: Limite de registros por página (máx recomendado: 100)
        """
        params: Dict[str, Any] = {
            "pagina": pagina,
            "itensPorPagina": min(itens_por_pagina, 100),
        }

        if numero_oab:
            params["numeroOab"] = str(numero_oab).strip()
        if uf_oab:
            params["ufOab"] = uf_oab.strip().upper()
        if numero_processo:
            params["numeroProcesso"] = str(numero_processo).strip()
        if nome_parte:
            params["nomeParte"] = nome_parte.strip()
        if sigla_tribunal:
            params["siglaTribunal"] = sigla_tribunal.strip().upper()
        if data_inicio:
            params["dataDisponibilizacaoInicio"] = data_inicio.strip()
        if data_fim:
            params["dataDisponibilizacaoFim"] = data_fim.strip()

        resp = self._request("GET", "comunicacao", params=params)
        dados = resp.json()
        return RespostaComunica.model_validate(dados)

    def iter_todas_comunicacoes(
        self,
        numero_oab: Optional[str] = None,
        uf_oab: Optional[str] = None,
        numero_processo: Optional[str] = None,
        nome_parte: Optional[str] = None,
        sigla_tribunal: Optional[str] = None,
        data_inicio: Optional[str] = None,
        data_fim: Optional[str] = None,
        itens_por_pagina: int = 50,
        max_paginas: Optional[int] = None
    ) -> Generator[Comunicacao, None, None]:
        """
        Iterador automático com paginação. Retorna uma a uma todas as comunicações encontradas.
        """
        pagina = 1
        while True:
            if max_paginas and pagina > max_paginas:
                break

            resposta = self.buscar_comunicacoes(
                numero_oab=numero_oab,
                uf_oab=uf_oab,
                numero_processo=numero_processo,
                nome_parte=nome_parte,
                sigla_tribunal=sigla_tribunal,
                data_inicio=data_inicio,
                data_fim=data_fim,
                pagina=pagina,
                itens_por_pagina=itens_por_pagina
            )

            if not resposta.items:
                break

            for item in resposta.items:
                yield item

            if len(resposta.items) < itens_por_pagina:
                break

            pagina += 1
            # Pausa suave para respeitar rate limits
            time.sleep(0.3)

    def baixar_certidao(self, hash_comunicacao: str, salvar_em: Optional[str] = None) -> bytes:
        """
        Baixa o PDF oficial da certidão comprobatória da intimação.

        :param hash_comunicacao: Hash único da comunicação retornado no campo `hash`
        :param salvar_em: Caminho opcional do arquivo PDF para gravar no disco
        :return: Conteúdo binário do PDF
        """
        if not hash_comunicacao:
            raise ValueError("O hash da comunicação é obrigatório para obter a certidão.")

        endpoint = f"comunicacao/{hash_comunicacao}/certidao"
        resp = self._request("GET", endpoint)

        conteudo = resp.content

        if salvar_em:
            destino = Path(salvar_em)
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(conteudo)
            logger.info("Certidão salva com sucesso em %s", destino)

        return conteudo

    def listar_tribunais(self) -> List[TribunalEstado]:
        """Retorna todos os tribunais integrados ao sistema Comunica PJe / DJEN."""
        resp = self._request("GET", "comunicacao/tribunal")
        dados = resp.json()
        return [TribunalEstado.model_validate(item) for item in dados]
