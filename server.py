import os
import asyncio
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Depends, Request, Response, Cookie
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response as FastAPIResponse, JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
from pydantic import BaseModel, Field, EmailStr

import config
from client import ComunicaPJeClient
from storage import CarolStorage
from notifier import CarolNotifier
from monitor import CarolMonitor
from auth import (
    verificar_hash_senha,
    gerar_secret_totp,
    gerar_uri_totp,
    gerar_qrcode_base64,
    validar_codigo_totp,
    gerar_token_sessao
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("carol.server")

# Inicialização dos componentes com suporte a PostgreSQL e BASE_URL
storage = CarolStorage()
client = ComunicaPJeClient()
notifier = CarolNotifier(storage=storage, base_url=config.BASE_URL)
motor = CarolMonitor(client=client, storage=storage, notifier=notifier)

# Dicionário em memória para tokens temporários durante fluxo 2FA (expiração de 5 minutos)
temp_2fa_tokens: Dict[str, Dict[str, Any]] = {}

# Flag para controle do scheduler em background
scheduler_running = True


async def background_scheduler():
    """Worker que roda a cada 60 segundos checando se alguma parte atingiu seu horário cron."""
    logger.info("Scheduler de background iniciado.")
    while scheduler_running:
        try:
            await asyncio.to_thread(motor.verificar_e_executar_agendadas)
        except Exception as e:
            logger.error("Erro no background scheduler: %s", e)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler_running
    scheduler_running = True
    task = asyncio.create_task(background_scheduler())
    yield
    scheduler_running = False
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="CAROL - Sistema de Notificações para Movimentações de Processos",
    description="Backend com autenticação segura, 2FA Google Authenticator, PostgreSQL e suporte a Proxy Reverso",
    version="2.1.0",
    lifespan=lifespan
)

# Suporte total a Proxy Reverso (Nginx, Traefik, Caddy, Cloudflare)
# Trata automaticamente X-Forwarded-Proto, X-Forwarded-Host e X-Forwarded-For
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

# --- Dependências de Autenticação ---

def obter_usuario_logado(request: Request) -> Optional[Dict[str, Any]]:
    token = request.cookies.get("carol_session")
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    if not token:
        return None

    return storage.validar_sessao(token)


def requer_autenticacao(usuario: Optional[Dict[str, Any]] = Depends(obter_usuario_logado)) -> Dict[str, Any]:
    if not usuario:
        raise HTTPException(status_code=401, detail="Não autenticado. Por favor, faça login.")
    return usuario


def requer_admin(usuario: Dict[str, Any] = Depends(requer_autenticacao)) -> Dict[str, Any]:
    if usuario.get("perfil") != "admin":
        raise HTTPException(status_code=403, detail="Acesso restrito a administradores.")
    return usuario


class SetupInicialSchema(BaseModel):
    nome: str = Field(..., min_length=2, max_length=120)
    email: EmailStr
    senha: str = Field(..., min_length=6, max_length=128)


class LoginSchema(BaseModel):
    email: EmailStr
    senha: str


class Login2FASchema(BaseModel):
    temp_token: str
    codigo_2fa: str


class Confirmar2FASchema(BaseModel):
    codigo_2fa: str


class Desativar2FASchema(BaseModel):
    senha: str


class UsuarioCriarSchema(BaseModel):
    nome: str = Field(..., min_length=2)
    email: EmailStr
    senha: str = Field(..., min_length=4)
    perfil: str = Field(default="operador")
    ativo: bool = Field(default=True)


class UsuarioAtualizarSchema(BaseModel):
    nome: str = Field(..., min_length=2)
    email: EmailStr
    perfil: str
    ativo: bool
    nova_senha: Optional[str] = None


class ParteCriarSchema(BaseModel):
    nome_parte: str = Field(..., min_length=2, description="Nome da parte a ser consultada")
    webhook_url: str = Field(..., description="URL de Webhook que receberá as notificações")
    cron_expression: str = Field(default="0 */2 * * *", description="Expressão cron padrão Linux")
    sigla_tribunal: Optional[str] = Field(default=None, description="Filtro opcional por tribunal (ex: TJSP)")
    ativo: bool = Field(default=True)
    data_inicio: Optional[str] = Field(default=None, description="Data inicial do monitoramento YYYY-MM-DD (opcional)")


class ParteAtualizarSchema(BaseModel):
    nome_parte: str = Field(..., min_length=2)
    webhook_url: str
    cron_expression: str
    sigla_tribunal: Optional[str] = None
    ativo: bool = True
    data_inicio: Optional[str] = None


# ==============================================================================
# ROTAS DE CONFIGURAÇÃO DO SISTEMA
# ==============================================================================

@app.get("/api/config")
def obter_configuracoes_publicas(request: Request):
    """Retorna a BASE_URL pública e tipo de banco ativo."""
    # Detecta se veio de proxy reverso
    url_proxy = str(request.base_url).rstrip("/")
    base_usada = config.BASE_URL if config.BASE_URL and "localhost" not in config.BASE_URL else url_proxy

    return {
        "base_url": base_usada,
        "base_url_env": config.BASE_URL,
        "banco_tipo": storage.db_type,
        "banco_descricao": "PostgreSQL (Produção)" if storage.db_type == "postgres" else "SQLite (Local)"
    }


# ==============================================================================
# ROTAS DE AUTENTICAÇÃO E 2FA
# ==============================================================================

@app.get("/api/auth/setup-status")
def setup_status():
    """Informa se o sistema necessita de configuração inicial (zero usuários cadastrados)."""
    total = storage.total_usuarios()
    return {
        "setup_necessario": (total == 0),
        "total_usuarios": total
    }


@app.post("/api/auth/setup-inicial")
def setup_inicial(dados: SetupInicialSchema, response: Response):
    """Permite o cadastro do primeiro Administrador quando não há usuários cadastrados."""
    if storage.total_usuarios() > 0:
        raise HTTPException(status_code=400, detail="A configuração inicial do sistema já foi realizada.")

    user_id = storage.cadastrar_usuario(
        nome=dados.nome,
        email=dados.email,
        senha=dados.senha,
        perfil="admin",
        ativo=True
    )

    token = storage.criar_sessao(user_id)
    response.set_cookie(
        key="carol_session",
        value=token,
        max_age=7 * 86400,
        httponly=True,
        samesite="lax",
        secure=False
    )

    usuario = storage.obter_usuario_por_id(user_id)
    return {
        "mensagem": "Administrador inicial configurado com sucesso!",
        "token": token,
        "usuario": {
            "id": usuario["id"],
            "nome": usuario["nome"],
            "email": usuario["email"],
            "perfil": usuario["perfil"]
        }
    }


@app.post("/api/auth/login")
def login(dados: LoginSchema, response: Response):
    usuario = storage.obter_usuario_por_email(dados.email)
    if not usuario or not usuario["ativo"]:
        raise HTTPException(status_code=401, detail="Email ou senha incorretos.")

    if not verificar_hash_senha(dados.senha, usuario["senha_hash"]):
        raise HTTPException(status_code=401, detail="Email ou senha incorretos.")

    if usuario["totp_habilitado"]:
        temp_token = gerar_token_sessao()
        temp_2fa_tokens[temp_token] = {
            "usuario_id": usuario["id"],
            "expira": datetime.now().timestamp() + 300
        }
        return {
            "status": "2fa_obrigatorio",
            "mensagem": "Autenticação em dois fatores necessária.",
            "temp_token": temp_token
        }

    token = storage.criar_sessao(usuario["id"])
    response.set_cookie(
        key="carol_session",
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
        samesite="lax",
        secure=False
    )

    return {
        "status": "sucesso",
        "usuario": {
            "id": usuario["id"],
            "nome": usuario["nome"],
            "email": usuario["email"],
            "perfil": usuario["perfil"],
            "totp_habilitado": bool(usuario["totp_habilitado"])
        }
    }


@app.post("/api/auth/login-2fa")
def login_2fa(dados: Login2FASchema, response: Response):
    temp = temp_2fa_tokens.get(dados.temp_token)
    if not temp or datetime.now().timestamp() > temp["expira"]:
        raise HTTPException(status_code=400, detail="Sessão de verificação expirada. Faça login novamente.")

    usuario = storage.obter_usuario_por_id(temp["usuario_id"])
    if not usuario or not usuario["totp_secret"]:
        raise HTTPException(status_code=400, detail="Configuração de 2FA inválida.")

    if not validar_codigo_totp(usuario["totp_secret"], dados.codigo_2fa):
        raise HTTPException(status_code=400, detail="Código de autenticação incorreto ou expirado.")

    del temp_2fa_tokens[dados.temp_token]

    token = storage.criar_sessao(usuario["id"])
    response.set_cookie(
        key="carol_session",
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
        samesite="lax",
        secure=False
    )

    return {
        "status": "sucesso",
        "usuario": {
            "id": usuario["id"],
            "nome": usuario["nome"],
            "email": usuario["email"],
            "perfil": usuario["perfil"],
            "totp_habilitado": True
        }
    }


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get("carol_session")
    if token:
        storage.encerrar_sessao(token)
    response.delete_cookie(key="carol_session")
    return {"status": "sucesso", "mensagem": "Sessão encerrada"}


@app.get("/api/auth/me")
def obter_meu_usuario(usuario: Dict[str, Any] = Depends(requer_autenticacao)):
    return {
        "id": usuario["id"],
        "nome": usuario["nome"],
        "email": usuario["email"],
        "perfil": usuario["perfil"],
        "totp_habilitado": bool(usuario["totp_habilitado"])
    }


@app.post("/api/auth/2fa/gerar")
def gerar_config_2fa(usuario: Dict[str, Any] = Depends(requer_autenticacao)):
    secret = gerar_secret_totp()
    storage.salvar_totp_secret_pendente(usuario["id"], secret)

    uri = gerar_uri_totp(usuario["email"], secret)
    qrcode_b64 = gerar_qrcode_base64(uri)

    return {
        "secret": secret,
        "totp_uri": uri,
        "qrcode_base64": qrcode_b64,
        "mensagem": "Escaneie o QR Code com o aplicativo Google Authenticator ou similar e digite o código de 6 dígitos gerado."
    }


@app.post("/api/auth/2fa/confirmar")
def confirmar_ativacao_2fa(dados: Confirmar2FASchema, usuario_atual: Dict[str, Any] = Depends(requer_autenticacao)):
    usuario = storage.obter_usuario_por_id(usuario_atual["id"])
    if not usuario or not usuario.get("totp_secret"):
        raise HTTPException(status_code=400, detail="Nenhum segredo 2FA foi gerado previamente.")

    if not validar_codigo_totp(usuario["totp_secret"], dados.codigo_2fa):
        raise HTTPException(status_code=400, detail="Código inválido. Verifique o horário do seu celular e tente novamente.")

    storage.ativar_totp(usuario["id"])
    return {"status": "sucesso", "mensagem": "Autenticação em dois fatores ativada com sucesso!"}


@app.post("/api/auth/2fa/desativar")
def desativar_2fa(dados: Desativar2FASchema, usuario_atual: Dict[str, Any] = Depends(requer_autenticacao)):
    usuario = storage.obter_usuario_por_id(usuario_atual["id"])
    if not verificar_hash_senha(dados.senha, usuario["senha_hash"]):
        raise HTTPException(status_code=400, detail="Senha incorreta.")

    storage.desativar_totp(usuario["id"])
    return {"status": "sucesso", "mensagem": "Autenticação em dois fatores desativada com sucesso."}


# ==============================================================================
# ÁREA ADMINISTRATIVA: GESTÃO DE USUÁRIOS
# ==============================================================================

@app.get("/api/usuarios")
def listar_usuarios(admin: Dict[str, Any] = Depends(requer_admin)):
    return storage.listar_usuarios()


@app.post("/api/usuarios")
def cadastrar_usuario(dados: UsuarioCriarSchema, admin: Dict[str, Any] = Depends(requer_admin)):
    existente = storage.obter_usuario_por_email(dados.email)
    if existente:
        raise HTTPException(status_code=400, detail="Já existe um usuário cadastrado com este e-mail.")

    usuario_id = storage.cadastrar_usuario(
        nome=dados.nome,
        email=dados.email,
        senha=dados.senha,
        perfil=dados.perfil,
        ativo=dados.ativo
    )
    return {"id": usuario_id, "mensagem": "Usuário cadastrado com sucesso!"}


@app.put("/api/usuarios/{usuario_id}")
def atualizar_usuario(usuario_id: int, dados: UsuarioAtualizarSchema, admin: Dict[str, Any] = Depends(requer_admin)):
    sucesso = storage.atualizar_usuario(
        usuario_id=usuario_id,
        nome=dados.nome,
        email=dados.email,
        perfil=dados.perfil,
        ativo=dados.ativo,
        nova_senha=dados.nova_senha
    )
    if not sucesso:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    return {"mensagem": "Usuário atualizado com sucesso!"}


@app.delete("/api/usuarios/{usuario_id}")
def excluir_usuario(usuario_id: int, admin: Dict[str, Any] = Depends(requer_admin)):
    if usuario_id == admin["id"]:
        raise HTTPException(status_code=400, detail="Você não pode excluir sua própria conta de administrador.")
    try:
        sucesso = storage.excluir_usuario(usuario_id)
        if not sucesso:
            raise HTTPException(status_code=404, detail="Usuário não encontrado.")
        return {"mensagem": "Usuário excluído com sucesso."}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/usuarios/{usuario_id}/resetar-2fa")
def resetar_2fa_usuario(usuario_id: int, admin: Dict[str, Any] = Depends(requer_admin)):
    storage.desativar_totp(usuario_id)
    return {"status": "sucesso", "mensagem": f"O 2FA do usuário #{usuario_id} foi resetado com sucesso."}


# ==============================================================================
# ROTAS DO SISTEMA (PARTES, MONITORAMENTO, COMUNICAÇÕES, WEBHOOKS)
# ==============================================================================

@app.get("/api/metricas")
def get_metricas(usuario: Dict[str, Any] = Depends(requer_autenticacao)):
    return storage.obter_metricas()


@app.get("/api/partes")
def listar_partes(usuario: Dict[str, Any] = Depends(requer_autenticacao)):
    return storage.listar_partes()


@app.post("/api/partes")
def criar_parte(dados: ParteCriarSchema, usuario: Dict[str, Any] = Depends(requer_autenticacao)):
    try:
        parte_id = storage.cadastrar_parte(
            nome_parte=dados.nome_parte,
            webhook_url=dados.webhook_url,
            cron_expression=dados.cron_expression,
            sigla_tribunal=dados.sigla_tribunal,
            ativo=dados.ativo,
            data_inicio=dados.data_inicio
        )
        return {"id": parte_id, "mensagem": "Parte cadastrada com sucesso!"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/partes/{parte_id}")
def obter_parte(parte_id: int, usuario: Dict[str, Any] = Depends(requer_autenticacao)):
    parte = storage.obter_parte(parte_id)
    if not parte:
        raise HTTPException(status_code=404, detail="Parte não encontrada")
    return parte


@app.put("/api/partes/{parte_id}")
def atualizar_parte(parte_id: int, dados: ParteAtualizarSchema, usuario: Dict[str, Any] = Depends(requer_autenticacao)):
    sucesso = storage.atualizar_parte(
        parte_id=parte_id,
        nome_parte=dados.nome_parte,
        webhook_url=dados.webhook_url,
        cron_expression=dados.cron_expression,
        sigla_tribunal=dados.sigla_tribunal,
        ativo=dados.ativo,
        data_inicio=dados.data_inicio
    )
    if not sucesso:
        raise HTTPException(status_code=404, detail="Parte não encontrada para atualização")
    return {"mensagem": "Parte atualizada com sucesso!"}


@app.delete("/api/partes/{parte_id}")
def excluir_parte(parte_id: int, usuario: Dict[str, Any] = Depends(requer_autenticacao)):
    sucesso = storage.excluir_parte(parte_id)
    if not sucesso:
        raise HTTPException(status_code=404, detail="Parte não encontrada")
    return {"mensagem": "Parte excluída com sucesso"}


@app.post("/api/partes/{parte_id}/consultar")
async def consultar_parte_agora(
    parte_id: int,
    dias: Optional[int] = Query(30, description="Dias retroativos. Passe 0 para histórico completo."),
    usuario: Dict[str, Any] = Depends(requer_autenticacao)
):
    parte = storage.obter_parte(parte_id)
    if not parte:
        raise HTTPException(status_code=404, detail="Parte não encontrada")

    dias_param = None if (dias is not None and dias <= 0) else dias
    novas = await asyncio.to_thread(motor.executar_varredura_parte, parte, dias_param)
    return {
        "mensagem": f"Consulta concluída para '{parte['nome_parte']}'.",
        "novas_atualizacoes": novas
    }


@app.post("/api/partes/{parte_id}/testar-webhook")
def testar_webhook(parte_id: int, usuario: Dict[str, Any] = Depends(requer_autenticacao)):
    parte = storage.obter_parte(parte_id)
    if not parte:
        raise HTTPException(status_code=404, detail="Parte não encontrada")

    url = parte["webhook_url"]
    if not url:
        raise HTTPException(status_code=400, detail="A parte não possui uma URL de webhook configurada")

    payload_teste = {
        "evento": "TESTE_CONEXAO_WEBHOOK",
        "timestamp": datetime.now().isoformat(),
        "base_url": notifier.base_url,
        "mensagem": "Este é um disparo de teste do sistema CAROL.",
        "parte": {
            "id": parte["id"],
            "nome": parte["nome_parte"]
        }
    }

    try:
        import requests
        resp = requests.post(url, json=payload_teste, timeout=10)
        return {
            "sucesso": 200 <= resp.status_code < 300,
            "status_code": resp.status_code,
            "resposta": resp.text[:500]
        }
    except Exception as e:
        return {
            "sucesso": False,
            "status_code": 0,
            "resposta": str(e)
        }


@app.post("/api/consultar-todas")
async def consultar_todas_agora(
    dias: Optional[int] = Query(30, description="Dias retroativos. Passe 0 para histórico completo."),
    usuario: Dict[str, Any] = Depends(requer_autenticacao)
):
    dias_param = None if (dias is not None and dias <= 0) else dias
    total = await asyncio.to_thread(motor.executar_todas_as_partes, dias_param)
    return {"mensagem": f"Varredura em todas as partes finalizada. Total de novidades notificadas: {total}"}


@app.get("/api/comunicacoes")
def listar_comunicacoes(
    parte_id: Optional[int] = Query(None, description="Filtro opcional por ID da Parte Monitorada"),
    limite: int = Query(50, le=200),
    usuario: Dict[str, Any] = Depends(requer_autenticacao)
):
    return storage.listar_comunicacoes_salvas(parte_id=parte_id, limite=limite)


@app.get("/api/comunicacoes/{hash_certidao}/certidao")
def baixar_certidao(hash_certidao: str):
    try:
        pdf_bytes = client.baixar_certidao(hash_certidao)
        return FastAPIResponse(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=certidao_{hash_certidao}.pdf"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao obter certidão do CNJ: {e}")


@app.get("/api/webhooks/historico")
def listar_historico_webhooks(limite: int = Query(50, le=200), usuario: Dict[str, Any] = Depends(requer_autenticacao)):
    return storage.listar_historico_webhooks(limite=limite)


@app.get("/api/tribunais")
def listar_tribunais(usuario: Dict[str, Any] = Depends(requer_autenticacao)):
    return client.listar_tribunais()


# ==============================================================================
# SERVIR FRONTEND ESTÁTICO
# ==============================================================================

static_dir = Path(__file__).parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
def get_index():
    index_file = static_dir / "index.html"
    return FileResponse(str(index_file))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
