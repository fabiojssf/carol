# AGENTS.md - Guia de Arquitetura e Engenharia para Modelos de IA (LLMs)

Este documento foi elaborado para fornecer a qualquer agente de inteligência artificial ou desenvolvedor todo o contexto técnico, premissas de negócio, arquitetura e convenções do projeto **CAROL - Sistema de Notificações para Movimentações de Processos**.

---

## 1. Visão Geral do Sistema

O **CAROL** é uma solução completa (Backend + Frontend + Scheduler + Autenticação 2FA + PostgreSQL) projetada para monitorar comunicações processuais (intimações, citações, editais e atas) centralizadas pelo Conselho Nacional de Justiça (**CNJ**) no **DJEN** (Diário de Justiça Eletrônico Nacional) e na plataforma **Comunica PJe** (`https://comunicaapi.pje.jus.br/api/v1`).

### O Problema Resolvido:
Tribunais de todo o Brasil (TJ, TRT, TRF, STJ, etc.) publicam atos processuais diariamente. Advogados e partes precisam ser avisados em tempo real assim que uma nova intimação for disponibilizada. O sistema CAROL:
1. Permite cadastrar e gerenciar **Usuários** com controle de acesso baseado em papéis (`admin` e `operador`).
2. Protege o acesso com **Autenticação em Dois Fatores (2FA)** via padrão **TOTP (RFC 6238)** compatível com **Google Authenticator**, Microsoft Authenticator, etc.
3. Permite cadastrar **Partes Processuais** (empresas ou pessoas físicas).
4. Permite associar uma **URL de Webhook** e uma **expressão Cron do Linux** individual para cada parte.
5. Suporta personalização da **`BASE_URL`** pública via variável de ambiente, garantindo que o sistema e seus webhooks nunca enviem links `localhost` quando operando atrás de um **Proxy Reverso** (Nginx, Traefik, Caddy, Cloudflare).
6. Persistência de alta performance em **PostgreSQL** para ambiente de produção, com pool de conexões via biblioteca moderna `psycopg` (v3).
7. Executa consultas automáticas na API pública do CNJ cobrindo uma janela retroativa de **30 dias** (1 mês para trás a partir da data da consulta).
8. Realiza um **Diff de Estado (Snapshot)**: se a consulta retornar as mesmas informações da checagem anterior, **nenhum webhook é disparado**. Somente se houver nova comunicação ou alteração de status/hash, um evento JSON estruturado é emitido.
9. Na aba de Movimentações Processuais, disponibiliza **filtro dinâmico por Parte Monitorada** e busca textual.
10. Baixa e armazena automaticamente as **Certidões Oficiais em PDF** emitidas pelo CNJ.

---

## 2. Diagrama de Arquitetura

```mermaid
graph TD
    User[Navegador Web / Usuário] -->|HTTPS / Proxy Reverso| Proxy[Proxy Reverso<br/>Nginx / Traefik / Caddy]
    Proxy -->|X-Forwarded-* Headers| API[Backend FastAPI<br/>server.py + ProxyHeaders]
    API -->|Login + 2FA TOTP| Auth[Módulo de Autenticação<br/>auth.py]
    Auth -->|Sessão Cookie| UI[Frontend Web Dashboard<br/>Vanilla HTML/CSS/JS]
    Scheduler[Worker de Background<br/>asyncio loop 60s] -->|Checa Próxima Consulta| Monitor[Motor de Monitoramento<br/>monitor.py]
    API --> Monitor
    Monitor -->|Consulta 30 Dias| CNJ[API Pública CNJ Comunica PJe<br/>comunicaapi.pje.jus.br/api/v1]
    Monitor -->|Diff de Snapshot| DB[(Banco PostgreSQL / SQLite<br/>carol_data)]
    Monitor -->|Novas Atualizações?| Notifier[Disparador de Notificações<br/>notifier.py]
    Notifier -->|HTTP POST JSON com BASE_URL| Webhook[Endpoints Externos<br/>n8n / Evolution API / WhatsApp / Slack]
    Notifier -->|Download PDF| StoragePDF[Pasta Local<br/>./certidoes/]
```

---

## 3. Configuração de Rede: BASE_URL e Proxy Reverso

Para que o sistema funcione corretamente em produção atrás de um proxy reverso e não envie links internos como `localhost` para os webhooks:

1. **Variável `BASE_URL` no `.env`**:
   ```env
   BASE_URL=https://carol.suaempresa.com.br
   ```
2. **Uso no Notificador ([notifier.py](notifier.py))**:
   - Os links de certidões e painel gerados no payload utilizam obrigatoriamente essa `BASE_URL`:
     ```python
     link_certidao_carol = f"{self.base_url}/api/comunicacoes/{c.hash}/certidao"
     link_painel_carol = f"{self.base_url}/"
     ```
3. **Suporte no FastAPI ([server.py](server.py))**:
   - O middleware `ProxyHeadersMiddleware(trusted_hosts="*")` do Uvicorn/Starlette é ativado para processar os cabeçalhos `X-Forwarded-Proto`, `X-Forwarded-Host` e `X-Forwarded-For`.

---

## 4. Banco de Dados: PostgreSQL (Produção) e SQLite (Fallback)

O sistema suporta **PostgreSQL** como banco principal de produção com pool de conexões gerenciado pela biblioteca `psycopg` (v3).

### Configuração no `.env`:
```env
# String de conexão completa:
DATABASE_URL=postgresql://carol_user:carol_secret_123@localhost:5432/carol_db

# Ou variáveis separadas:
POSTGRES_USER=carol_user
POSTGRES_PASSWORD=carol_secret_123
POSTGRES_DB=carol_db
POSTGRES_HOST=db
POSTGRES_PORT=5432
```

### Tabelas Principais:
1. `usuarios`:
   - `id`: SERIAL PRIMARY KEY
   - `nome`: TEXT NOT NULL
   - `email`: TEXT UNIQUE NOT NULL
   - `senha_hash`: TEXT NOT NULL (bcrypt)
   - `perfil`: TEXT ('admin' ou 'operador')
   - `ativo`: INTEGER (1 ou 0)
   - `totp_secret`: TEXT (segredo base32)
   - `totp_habilitado`: INTEGER (1 ou 0)

2. `sessoes_ativas`:
   - `token`: TEXT PRIMARY KEY
   - `usuario_id`: INTEGER (FK usuarios ON DELETE CASCADE)
   - `expira_em`: TIMESTAMP

3. `partes_monitoramento`:
   - `id`: SERIAL PRIMARY KEY
   - `nome_parte`: TEXT NOT NULL
   - `webhook_url`: TEXT NOT NULL
   - `cron_expression`: TEXT (padrão `0 */2 * * *`)
   - `sigla_tribunal`: TEXT NULL (filtro opcional)
   - `data_inicio`: TEXT NULL (data inicial personalizada YYYY-MM-DD; data final é sempre a data atual)
   - `ativo`: INTEGER (1 ou 0)
   - `ultima_consulta`: TIMESTAMP
   - `proxima_consulta`: TIMESTAMP
   - `total_notificacoes`: INTEGER DEFAULT 0

4. `snapshots_comunicacoes`:
   - `id_comunicacao`: INTEGER NOT NULL
   - `parte_id`: INTEGER NOT NULL (FK ON DELETE CASCADE)
   - `hash`: TEXT
   - `status`: TEXT
   - `numero_processo`, `sigla_tribunal`, `tipo_comunicacao`, `data_disponibilizacao`, `texto_resumo`, `link`
   - `PRIMARY KEY (id_comunicacao, parte_id)`

5. `historico_webhooks`:
   - `id`: SERIAL PRIMARY KEY
   - `parte_id`: INTEGER (FK)
   - `comunicacao_id`: INTEGER
   - `webhook_url`: TEXT
   - `status_code`: INTEGER
   - `sucesso`: INTEGER (1 ou 0)
   - `payload`: TEXT JSON
   - `resposta`: TEXT
   - `enviado_em`: TIMESTAMP

---

## 5. Formato do Payload do Webhook

Disparado via `HTTP POST` com `Content-Type: application/json` formatado com a `BASE_URL`:

```json
{
  "evento": "ATUALIZACAO_PROCESSUAL",
  "timestamp": "2026-11-01T02:15:00.000000",
  "base_url": "https://carol.suaempresa.com.br",
  "parte_monitorada": {
    "id": 1,
    "nome": "BANCO BRADESCO S.A.",
    "tribunal_filtro": "TJSP"
  },
  "comunicacao": {
    "id": 741846636,
    "numero_processo": "00015896820268160107",
    "numero_processo_mascara": "0001589-68.2026.8.16.0107",
    "sigla_tribunal": "TJPR",
    "nome_orgao": "Juiz das Garantias da Vara Criminal de Mamborê",
    "tipo_comunicacao": "Intimação",
    "tipo_documento": "Conclusão",
    "nome_classe": "RESTITUIÇÃO DE COISAS APREENDIDAS",
    "data_disponibilizacao": "2026-10-30",
    "meio": "Diário de Justiça Eletrônico Nacional",
    "texto_resumo": "PODER JUDICIÁRIO DO ESTADO DO PARANÁ...",
    "link_autos": "https://projudi.tjpr.jus.br/...",
    "hash_certidao": "jlx8NKdwzRKrcohPTKe77yYbD1mrEX",
    "link_certidao_api": "https://comunicaapi.pje.jus.br/api/v1/comunicacao/jlx8NKdwzRKrcohPTKe77yYbD1mrEX/certidao",
    "link_certidao_carol": "https://carol.suaempresa.com.br/api/comunicacoes/jlx8NKdwzRKrcohPTKe77yYbD1mrEX/certidao",
    "link_painel_carol": "https://carol.suaempresa.com.br/",
    "arquivo_certidao_local": "certidoes/00015896820268160107_741846636.pdf",
    "destinatarios": [
      { "comunicacao_id": 741846636, "nome": "PARTE INTERESSADA", "polo": "P" }
    ],
    "advogados": [
      { "nome": "DR. ADVOGADO", "numero_oab": "12345", "uf_oab": "SP" }
    ]
  }
}
```

---

## 6. Autenticação, 2FA e Onboarding Inicial Seguro

1. **Onboarding Inicial Dinâmico (Setup Seguro)**:
   - Se o banco de dados for novo e não possuir nenhum usuário (`total_usuarios == 0`), o endpoint `GET /api/auth/setup-status` sinaliza `setup_necessario: true`.
   - A interface web apresenta automaticamente o formulário de cadastro do **Primeiro Administrador** (`POST /api/auth/setup-inicial`).
   - Nenhuma credencial padrão ou hardcoded é exibida na tela inicial.
   - Assim que o primeiro administrador é criado, o endpoint de setup é permanentemente bloqueado (retornando erro 400), e o sistema passa a exigir autenticação normal (Login + Senha + 2FA).
2. **Credenciais Primárias**: E-mail e senha com hash seguro utilizando a biblioteca `bcrypt`.
3. **Segundo Fator (TOTP - RFC 6238)**:
   - Geração de segredo Base32 via `pyotp.random_base32()`.
   - Renderização de QR Code PNG em base64 via biblioteca `qrcode` para captura com a câmera do smartphone no Google Authenticator / Microsoft Authenticator.

---

## 7. Como Executar e Deploy com Docker

### Via Docker Compose (Recomendado para Produção com PostgreSQL):
```bash
docker compose up -d --build
```
Isso sobe automaticamente o contêiner do **PostgreSQL 16** com volume nomeado `postgres_data` e o servidor web **CAROL** com auto-recuperação.

### Localmente (Desenvolvimento):
```bash
source .venv/bin/activate
uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```
Acesse no navegador: `http://localhost:8000` (ou sua `BASE_URL`).

---

## 8. Diretrizes para Agentes de IA em Manutenções Futuras

1. **Preservar a compatibilidade PostgreSQL/SQLite:** Mantenha as consultas DML/DDL compatíveis em [storage.py](storage.py) utilizando `_execute`, `_fetchone` e `_fetchall`.
2. **Respeitar a BASE_URL:** Sempre utilize `self.base_url` em [notifier.py](notifier.py) para gerar links enviados para webhooks e integrações. Nunca insira `localhost` hardcoded.
3. **Preservar a regra do Diff e Janela de 30 Dias:** O teste de igualdade de snapshot e a janela retroativa de 30 dias são regras de negócio fundamentais do sistema.
