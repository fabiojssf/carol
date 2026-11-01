import re
from typing import Optional, List, Any
from pydantic import BaseModel, ConfigDict, Field


class Advogado(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = None
    nome: Optional[str] = None
    numero_oab: Optional[str] = None
    uf_oab: Optional[str] = None


class DestinatarioAdvogado(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: Optional[int] = None
    comunicacao_id: Optional[int] = None
    advogado_id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    advogado: Optional[Advogado] = None


class Destinatario(BaseModel):
    model_config = ConfigDict(extra="ignore")

    comunicacao_id: Optional[int] = None
    nome: Optional[str] = None
    polo: Optional[str] = None


class Comunicacao(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    data_disponibilizacao: Optional[str] = None
    siglaTribunal: Optional[str] = None
    tipoComunicacao: Optional[str] = None
    nomeOrgao: Optional[str] = None
    idOrgao: Optional[int] = None
    texto: Optional[str] = None
    numero_processo: Optional[str] = None
    numeroprocessocommascara: Optional[str] = None
    meio: Optional[str] = None
    meiocompleto: Optional[str] = None
    link: Optional[str] = None
    tipoDocumento: Optional[str] = None
    nomeClasse: Optional[str] = None
    codigoClasse: Optional[str] = None
    numeroComunicacao: Optional[int] = None
    ativo: Optional[bool] = None
    hash: Optional[str] = None
    status: Optional[str] = None
    motivo_cancelamento: Optional[str] = None
    data_cancelamento: Optional[str] = None
    destinatarios: List[Destinatario] = Field(default_factory=list)
    destinatarioadvogados: List[DestinatarioAdvogado] = Field(default_factory=list)

    @property
    def texto_limpo(self) -> str:
        """Remove tags HTML e normaliza espaços para leitura direta."""
        if not self.texto:
            return ""
        clean = re.sub(r"<[^>]+>", " ", self.texto)
        clean = re.sub(r"\s+", " ", clean).strip()
        clean = (
            clean.replace("&nbsp;", " ")
            .replace("&ordm;", "º")
            .replace("&ordf;", "ª")
            .replace("&iacute;", "í")
            .replace("&eacute;", "é")
            .replace("&aacute;", "á")
            .replace("&atilde;", "ã")
            .replace("&ccedil;", "ç")
            .replace("&otilde;", "õ")
            .replace("&oacute;", "ó")
            .replace("&uacute;", "ú")
        )
        return clean

    @property
    def advogados_nomes(self) -> List[str]:
        nomes = []
        for da in self.destinatarioadvogados:
            if da.advogado and da.advogado.nome:
                nomes.append(da.advogado.nome)
        return nomes


class RespostaComunica(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: str
    message: Optional[str] = None
    count: int = 0
    items: List[Comunicacao] = Field(default_factory=list)


class InstituicaoTribunal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sigla: str
    nome: str
    dataUltimoEnvio: Optional[str] = None
    active: Optional[bool] = True


class TribunalEstado(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uf: str
    nomeEstado: str
    instituicoes: List[InstituicaoTribunal] = Field(default_factory=list)
