import sqlite3
import json
import logging
from typing import List, Dict, Any, Optional, Tuple, Generator
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import contextmanager
from croniter import croniter

from models import Comunicacao
from auth import gerar_hash_senha, gerar_token_sessao
import config

logger = logging.getLogger("carol.storage")

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    PSYCOPG_AVAILABLE = True
except ImportError:
    PSYCOPG_AVAILABLE = False


class CarolStorage:
    """
    Camada de persistência para o CAROL.
    Suporta PostgreSQL de alta performance (produção) com fallback transparente para SQLite (desenvolvimento local).
    """

    def __init__(self, database_url: Optional[str] = None, sqlite_path: Optional[Any] = None):
        self.db_url = database_url or config.DATABASE_URL
        self.db_type = "sqlite"
        self.pg_pool = None
        self.sqlite_path = Path(sqlite_path) if sqlite_path else Path(config.SQLITE_DB_PATH)

        if self.db_url and (self.db_url.startswith("postgres://") or self.db_url.startswith("postgresql://")):
            if PSYCOPG_AVAILABLE:
                try:
                    # Converte postgres:// para postgresql:// se necessário
                    fixed_url = self.db_url.replace("postgres://", "postgresql://", 1)
                    # Testa a conexão imediata
                    with psycopg.connect(fixed_url, connect_timeout=3) as conn:
                        pass
                    
                    # Inicializa o pool de conexões para produção
                    self.pg_pool = ConnectionPool(
                        conninfo=fixed_url,
                        min_size=2,
                        max_size=15,
                        kwargs={"row_factory": dict_row}
                    )
                    self.db_type = "postgres"
                    logger.info("Conectado com sucesso ao PostgreSQL (Produção): %s", fixed_url.split("@")[-1])
                except Exception as e:
                    logger.warning("Não foi possível conectar ao PostgreSQL (%s). Utilizando SQLite de fallback.", e)
                    self.db_type = "sqlite"
            else:
                logger.warning("Driver psycopg não disponível. Utilizando SQLite.")
                self.db_type = "sqlite"

        if self.db_type == "sqlite":
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            logger.info("Utilizando banco SQLite local: %s", self.sqlite_path)

        self._init_db()

    @contextmanager
    def _get_connection(self):
        """Retorna uma conexão ativa (do pool no PostgreSQL ou local no SQLite)."""
        if self.db_type == "postgres" and self.pg_pool:
            with self.pg_pool.connection() as conn:
                yield conn
        else:
            conn = sqlite3.connect(str(self.sqlite_path))
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            try:
                yield conn
            finally:
                conn.close()

    def _execute(self, query: str, params: tuple = ()) -> Any:
        """Executa comandos DML/DDL normalizando os placeholders (? para %s no Postgres)."""
        with self._get_connection() as conn:
            if self.db_type == "postgres":
                pg_query = query.replace("?", "%s")
                with conn.cursor() as cur:
                    cur.execute(pg_query, params)
                    conn.commit()
                    return cur
            else:
                cur = conn.execute(query, params)
                conn.commit()
                return cur

    def _fetchone(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            if self.db_type == "postgres":
                pg_query = query.replace("?", "%s")
                with conn.cursor() as cur:
                    cur.execute(pg_query, params)
                    row = cur.fetchone()
                    conn.commit()
                    return dict(row) if row else None
            else:
                cur = conn.execute(query, params)
                row = cur.fetchone()
                conn.commit()
                return dict(row) if row else None

    def _fetchall(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            if self.db_type == "postgres":
                pg_query = query.replace("?", "%s")
                with conn.cursor() as cur:
                    cur.execute(pg_query, params)
                    rows = cur.fetchall()
                    return [dict(r) for r in rows]
            else:
                cur = conn.execute(query, params)
                rows = cur.fetchall()
                return [dict(r) for r in rows]

    def _init_db(self):
        """Cria as tabelas caso não existam."""
        id_serial = "SERIAL PRIMARY KEY" if self.db_type == "postgres" else "INTEGER PRIMARY KEY AUTOINCREMENT"

        with self._get_connection() as conn:
            # 1. Tabela de Usuários
            query_usuarios = f"""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id {id_serial},
                    nome TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    senha_hash TEXT NOT NULL,
                    perfil TEXT NOT NULL DEFAULT 'admin',
                    ativo INTEGER DEFAULT 1,
                    totp_secret TEXT,
                    totp_habilitado INTEGER DEFAULT 0,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            
            # 2. Tabela de Sessões Ativas
            query_sessoes = """
                CREATE TABLE IF NOT EXISTS sessoes_ativas (
                    token TEXT PRIMARY KEY,
                    usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expira_em TIMESTAMP NOT NULL
                )
            """

            # 3. Tabela de Partes Monitoradas
            query_partes = f"""
                CREATE TABLE IF NOT EXISTS partes_monitoramento (
                    id {id_serial},
                    nome_parte TEXT NOT NULL,
                    webhook_url TEXT NOT NULL,
                    cron_expression TEXT NOT NULL DEFAULT '0 */2 * * *',
                    sigla_tribunal TEXT,
                    data_inicio TEXT,
                    ativo INTEGER DEFAULT 1,
                    ultima_consulta TIMESTAMP,
                    proxima_consulta TIMESTAMP,
                    total_notificacoes INTEGER DEFAULT 0,
                    criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """

            # 4. Tabela de Snapshots de Comunicações
            query_snapshots = """
                CREATE TABLE IF NOT EXISTS snapshots_comunicacoes (
                    id_comunicacao INTEGER NOT NULL,
                    parte_id INTEGER NOT NULL REFERENCES partes_monitoramento(id) ON DELETE CASCADE,
                    hash TEXT,
                    numero_processo TEXT,
                    sigla_tribunal TEXT,
                    tipo_comunicacao TEXT,
                    data_disponibilizacao TEXT,
                    texto_resumo TEXT,
                    link TEXT,
                    status TEXT,
                    capturado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (id_comunicacao, parte_id)
                )
            """

            # 5. Tabela de Histórico de Webhooks
            query_webhooks = f"""
                CREATE TABLE IF NOT EXISTS historico_webhooks (
                    id {id_serial},
                    parte_id INTEGER NOT NULL REFERENCES partes_monitoramento(id) ON DELETE CASCADE,
                    comunicacao_id INTEGER,
                    numero_processo TEXT,
                    webhook_url TEXT NOT NULL,
                    status_code INTEGER,
                    sucesso INTEGER DEFAULT 1,
                    payload TEXT,
                    resposta TEXT,
                    enviado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """

            if self.db_type == "postgres":
                with conn.cursor() as cur:
                    cur.execute(query_usuarios)
                    cur.execute(query_sessoes)
                    cur.execute(query_partes)
                    cur.execute(query_snapshots)
                    cur.execute(query_webhooks)
                    conn.commit()
            else:
                conn.execute(query_usuarios)
                conn.execute(query_sessoes)
                conn.execute(query_partes)
                conn.execute(query_snapshots)
                conn.execute(query_webhooks)
                conn.commit()

        # Migração transparente da coluna data_inicio caso o banco já existisse
        try:
            self._execute("ALTER TABLE partes_monitoramento ADD COLUMN data_inicio TEXT")
        except Exception:
            pass

    # --- Autenticação e Gestão de Usuários ---

    def total_usuarios(self) -> int:
        """Retorna o número total de usuários cadastrados no sistema."""
        row = self._fetchone("SELECT COUNT(*) as total FROM usuarios")
        return row.get("total", 0) if row else 0

    def cadastrar_usuario(
        self,
        nome: str,
        email: str,
        senha: str,
        perfil: str = "operador",
        ativo: bool = True
    ) -> int:
        # Se for o primeiro usuário do sistema, força o perfil como 'admin'
        if self.total_usuarios() == 0:
            perfil = "admin"

        query = """
            INSERT INTO usuarios (nome, email, senha_hash, perfil, ativo, totp_habilitado)
            VALUES (?, ?, ?, ?, ?, 0)
            RETURNING id
        """
        row = self._fetchone(query, (nome.strip(), email.strip().lower(), gerar_hash_senha(senha), perfil, 1 if ativo else 0))
        return row["id"]

    def atualizar_usuario(
        self,
        usuario_id: int,
        nome: str,
        email: str,
        perfil: str,
        ativo: bool,
        nova_senha: Optional[str] = None
    ) -> bool:
        if nova_senha and nova_senha.strip():
            query = """
                UPDATE usuarios SET
                    nome = ?, email = ?, senha_hash = ?, perfil = ?, ativo = ?, atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ?
            """
            params = (nome.strip(), email.strip().lower(), gerar_hash_senha(nova_senha), perfil, 1 if ativo else 0, usuario_id)
        else:
            query = """
                UPDATE usuarios SET
                    nome = ?, email = ?, perfil = ?, ativo = ?, atualizado_em = CURRENT_TIMESTAMP
                WHERE id = ?
            """
            params = (nome.strip(), email.strip().lower(), perfil, 1 if ativo else 0, usuario_id)

        self._execute(query, params)
        return True

    def excluir_usuario(self, usuario_id: int) -> bool:
        total_admins = self._fetchone("SELECT COUNT(*) as total FROM usuarios WHERE perfil = 'admin' AND ativo = 1")
        total = total_admins.get("total", 0) if total_admins else 0
        usuario = self.obter_usuario_por_id(usuario_id)

        if usuario and usuario["perfil"] == "admin" and total <= 1:
            raise ValueError("Não é possível excluir o único administrador ativo do sistema.")

        self._execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
        return True

    def obter_usuario_por_email(self, email: str) -> Optional[Dict[str, Any]]:
        return self._fetchone("SELECT * FROM usuarios WHERE email = ?", (email.strip().lower(),))

    def obter_usuario_por_id(self, usuario_id: int) -> Optional[Dict[str, Any]]:
        return self._fetchone("SELECT * FROM usuarios WHERE id = ?", (usuario_id,))

    def listar_usuarios(self) -> List[Dict[str, Any]]:
        return self._fetchall("SELECT id, nome, email, perfil, ativo, totp_habilitado, criado_em FROM usuarios ORDER BY id ASC")

    # --- 2FA (TOTP) ---

    def salvar_totp_secret_pendente(self, usuario_id: int, secret: str):
        self._execute("UPDATE usuarios SET totp_secret = ? WHERE id = ?", (secret, usuario_id))

    def ativar_totp(self, usuario_id: int):
        self._execute("UPDATE usuarios SET totp_habilitado = 1 WHERE id = ?", (usuario_id,))

    def desativar_totp(self, usuario_id: int):
        self._execute("UPDATE usuarios SET totp_habilitado = 0, totp_secret = NULL WHERE id = ?", (usuario_id,))

    # --- Sessões Ativas ---

    def criar_sessao(self, usuario_id: int, duracao_dias: int = 7) -> str:
        token = gerar_token_sessao()
        expira_em = datetime.now() + timedelta(days=duracao_dias)
        self._execute("""
            INSERT INTO sessoes_ativas (token, usuario_id, expira_em)
            VALUES (?, ?, ?)
        """, (token, usuario_id, expira_em.strftime("%Y-%m-%d %H:%M:%S")))
        return token

    def validar_sessao(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None
        agora_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        query = """
            SELECT u.id, u.nome, u.email, u.perfil, u.ativo, u.totp_habilitado
            FROM sessoes_ativas s
            JOIN usuarios u ON s.usuario_id = u.id
            WHERE s.token = ? AND s.expira_em > ? AND u.ativo = 1
        """
        return self._fetchone(query, (token, agora_str))

    def encerrar_sessao(self, token: str):
        if token:
            self._execute("DELETE FROM sessoes_ativas WHERE token = ?", (token,))

    # --- CRUD de Partes ---

    def calcular_proxima_execucao(self, cron_expr: str, base_time: Optional[datetime] = None) -> str:
        try:
            base = base_time or datetime.now()
            iterador = croniter(cron_expr.strip(), base)
            prox = iterador.get_next(datetime)
            return prox.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            iterador = croniter("0 */2 * * *", datetime.now())
            return iterador.get_next(datetime).strftime("%Y-%m-%d %H:%M:%S")

    def cadastrar_parte(
        self,
        nome_parte: str,
        webhook_url: str,
        cron_expression: str = "0 */2 * * *",
        sigla_tribunal: Optional[str] = None,
        ativo: bool = True,
        data_inicio: Optional[str] = None
    ) -> int:
        proxima = self.calcular_proxima_execucao(cron_expression)
        query = """
            INSERT INTO partes_monitoramento (
                nome_parte, webhook_url, cron_expression, sigla_tribunal, ativo, proxima_consulta, data_inicio
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING id
        """
        row = self._fetchone(query, (
            nome_parte.strip(),
            webhook_url.strip(),
            cron_expression.strip(),
            sigla_tribunal.strip().upper() if sigla_tribunal else None,
            1 if ativo else 0,
            proxima,
            data_inicio.strip() if data_inicio and data_inicio.strip() else None
        ))
        return row["id"]

    def atualizar_parte(
        self,
        parte_id: int,
        nome_parte: str,
        webhook_url: str,
        cron_expression: str,
        sigla_tribunal: Optional[str] = None,
        ativo: bool = True,
        data_inicio: Optional[str] = None
    ) -> bool:
        proxima = self.calcular_proxima_execucao(cron_expression)
        query = """
            UPDATE partes_monitoramento SET
                nome_parte = ?,
                webhook_url = ?,
                cron_expression = ?,
                sigla_tribunal = ?,
                ativo = ?,
                proxima_consulta = ?,
                data_inicio = ?,
                atualizado_em = CURRENT_TIMESTAMP
            WHERE id = ?
        """
        self._execute(query, (
            nome_parte.strip(),
            webhook_url.strip(),
            cron_expression.strip(),
            sigla_tribunal.strip().upper() if sigla_tribunal else None,
            1 if ativo else 0,
            proxima,
            data_inicio.strip() if data_inicio and data_inicio.strip() else None,
            parte_id
        ))
        return True

    def excluir_parte(self, parte_id: int) -> bool:
        self._execute("DELETE FROM partes_monitoramento WHERE id = ?", (parte_id,))
        return True

    def obter_parte(self, parte_id: int) -> Optional[Dict[str, Any]]:
        return self._fetchone("SELECT * FROM partes_monitoramento WHERE id = ?", (parte_id,))

    def listar_partes(self) -> List[Dict[str, Any]]:
        return self._fetchall("SELECT * FROM partes_monitoramento ORDER BY id DESC")

    def atualizar_execucao_parte(self, parte_id: int, cron_expr: str):
        agora = datetime.now()
        proxima = self.calcular_proxima_execucao(cron_expr, base_time=agora)
        self._execute("""
            UPDATE partes_monitoramento SET
                ultima_consulta = ?,
                proxima_consulta = ?
            WHERE id = ?
        """, (agora.strftime("%Y-%m-%d %H:%M:%S"), proxima, parte_id))

    def incrementar_notificacoes_parte(self, parte_id: int, quantidade: int = 1):
        self._execute("""
            UPDATE partes_monitoramento
            SET total_notificacoes = total_notificacoes + ?
            WHERE id = ?
        """, (quantidade, parte_id))

    # --- Diff de Snapshot e Detecção de Mudança de Estado ---

    def identificar_novas_ou_atualizadas(
        self,
        parte_id: int,
        comunicacoes_atuais: List[Comunicacao]
    ) -> List[Comunicacao]:
        cursor_rows = self._fetchall(
            "SELECT id_comunicacao, hash, status FROM snapshots_comunicacoes WHERE parte_id = ?",
            (parte_id,)
        )
        snapshot_anterior = {row["id_comunicacao"]: {"hash": row["hash"], "status": row["status"]} for row in cursor_rows}

        modificadas_ou_novas: List[Comunicacao] = []

        for c in comunicacoes_atuais:
            anterior = snapshot_anterior.get(c.id)

            if anterior is None:
                modificadas_ou_novas.append(c)
            elif anterior["hash"] != c.hash or anterior["status"] != c.status:
                modificadas_ou_novas.append(c)

            # Inserção / Atualização de snapshot (compatível com Postgres e SQLite)
            self._execute("""
                INSERT INTO snapshots_comunicacoes (
                    id_comunicacao, parte_id, hash, numero_processo, sigla_tribunal,
                    tipo_comunicacao, data_disponibilizacao, texto_resumo, link, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id_comunicacao, parte_id) DO UPDATE SET
                    hash = excluded.hash,
                    status = excluded.status,
                    texto_resumo = excluded.texto_resumo,
                    capturado_em = CURRENT_TIMESTAMP
            """, (
                c.id,
                parte_id,
                c.hash,
                c.numeroprocessocommascara or c.numero_processo,
                c.siglaTribunal,
                c.tipoComunicacao,
                c.data_disponibilizacao,
                c.texto_limpo[:300],
                c.link,
                c.status
            ))

        return modificadas_ou_novas

    # --- Histórico de Webhooks ---

    def registrar_webhook_disparado(
        self,
        parte_id: int,
        comunicacao_id: Optional[int],
        numero_processo: Optional[str],
        webhook_url: str,
        status_code: int,
        sucesso: bool,
        payload: Dict[str, Any],
        resposta_texto: str
    ):
        self._execute("""
            INSERT INTO historico_webhooks (
                parte_id, comunicacao_id, numero_processo, webhook_url,
                status_code, sucesso, payload, resposta
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            parte_id,
            comunicacao_id,
            numero_processo,
            webhook_url,
            status_code,
            1 if sucesso else 0,
            json.dumps(payload, ensure_ascii=False),
            resposta_texto[:1000]
        ))

    def listar_historico_webhooks(self, limite: int = 50) -> List[Dict[str, Any]]:
        return self._fetchall("""
            SELECT h.*, p.nome_parte
            FROM historico_webhooks h
            LEFT JOIN partes_monitoramento p ON h.parte_id = p.id
            ORDER BY h.id DESC
            LIMIT ?
        """, (limite,))

    def listar_comunicacoes_salvas(self, parte_id: Optional[int] = None, limite: int = 100) -> List[Dict[str, Any]]:
        if parte_id:
            query = """
                SELECT s.*, p.nome_parte
                FROM snapshots_comunicacoes s
                JOIN partes_monitoramento p ON s.parte_id = p.id
                WHERE s.parte_id = ?
                ORDER BY s.capturado_em DESC LIMIT ?
            """
            return self._fetchall(query, (parte_id, limite))
        else:
            query = """
                SELECT s.*, p.nome_parte
                FROM snapshots_comunicacoes s
                JOIN partes_monitoramento p ON s.parte_id = p.id
                ORDER BY s.capturado_em DESC LIMIT ?
            """
            return self._fetchall(query, (limite,))

    def obter_metricas(self) -> Dict[str, int]:
        total_partes = self._fetchone("SELECT COUNT(*) as t FROM partes_monitoramento")
        total_partes_ativas = self._fetchone("SELECT COUNT(*) as t FROM partes_monitoramento WHERE ativo = 1")
        total_comunicacoes = self._fetchone("SELECT COUNT(*) as t FROM snapshots_comunicacoes")
        total_webhooks = self._fetchone("SELECT COUNT(*) as t FROM historico_webhooks")
        total_usuarios = self._fetchone("SELECT COUNT(*) as t FROM usuarios")

        return {
            "total_partes": total_partes.get("t", 0) if total_partes else 0,
            "total_partes_ativas": total_partes_ativas.get("t", 0) if total_partes_ativas else 0,
            "total_comunicacoes": total_comunicacoes.get("t", 0) if total_comunicacoes else 0,
            "total_webhooks": total_webhooks.get("t", 0) if total_webhooks else 0,
            "total_usuarios": total_usuarios.get("t", 0) if total_usuarios else 0,
            "banco_tipo": self.db_type
        }
