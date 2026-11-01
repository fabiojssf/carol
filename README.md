# CAROL - Sistema de Notificações para Movimentações de Processos

Sistema autônomo e cliente Python de alta performance para consulta e monitoramento em tempo real de comunicações, intimações e movimentações processuais centralizadas pelo Conselho Nacional de Justiça (**CNJ**) no **DJEN** e **Comunica PJe** (`https://comunicaapi.pje.jus.br/api/v1`).

---

## 🚀 Funcionalidades

- **Sem necessidade de certificado digital ou login**: Consulta direta via API REST pública oficial do CNJ.
- **Tipagem Forte (Pydantic v2)**: Modelos estritos para Processo, Advogado, Destinatários e Metadados.
- **Monitoramento Periódico Autônomo**: Varredura contínua de OABs e processos cadastrados com intervalo configurável.
- **Prevenção de Notificações Duplicadas**: Histórico local em SQLite para garantir que cada intimação seja notificada exatamente uma vez.
- **Download Automático de Certidões PDF**: Baixa e salva a comprovação oficial da publicação emitida pelo CNJ.
- **Notificador Multicanal**:
  - Terminal com design interativo e colorido (Rich).
  - Webhook REST (compatível com Discord, Slack, n8n, WhatsApp API, Zapier).
- **Proteção contra Rate-Limiting**: Gerenciamento inteligente de limites (`x-ratelimit-remaining`) e backoff exponencial em caso de status 429.

---

## 📁 Estrutura do Projeto

```text
.
├── client.py        # Cliente HTTP ComunicaPJeClient (paginação, filtros, certidões)
├── models.py        # Modelos de dados Pydantic v2 (Comunicacao, Advogado, etc.)
├── storage.py       # Gerenciador do banco de dados SQLite local
├── notifier.py      # Formatador de alertas visuais, webhooks e download de PDF
├── monitor.py       # Motor de monitoramento autônomo contínuo
├── cli.py           # Interface de linha de comando (CLI)
├── requirements.txt # Dependências do projeto
└── .env.example     # Modelo de configuração de variáveis de ambiente
```

---

## ⚡ Instalação e Configuração

O ambiente virtual já foi preparado com o `uv`. Para ativá-lo:

```bash
# Ativar o ambiente virtual
source .venv/bin/activate

# Ou executar diretamente com .venv/bin/python
```

Se desejar configurar notificações via Webhook (Discord, Slack ou WhatsApp):
```bash
cp .env.example .env
# Edite o arquivo .env e adicione a URL do seu webhook
```

---

## 🛠️ Como Usar (CLI)

### 1. Consultar Intimações por OAB
```bash
python cli.py buscar --oab 123456 --uf SP --limite 5
```

### 2. Consultar por Número do Processo (CNJ)
```bash
python cli.py buscar --processo 0001589-68.2026.8.16.0107
```

### 3. Cadastrar Alvos para o Monitoramento Contínuo
Cadastre as OABs ou os números de processos que o CAROL deve vigiar:
```bash
# Cadastrar OAB
python cli.py adicionar-oab 123456 SP --nome "Dr. Advogado Responsável"

# Cadastrar Processo
python cli.py adicionar-processo 0001589-68.2026.8.16.0107 --descricao "Ação de Cobrança"
```

### 4. Listar Alvos Cadastrados
```bash
python cli.py listar-alvos
```

### 5. Iniciar o Monitoramento Automático
Inicia o serviço para verificar novas publicações a cada X minutos (padrão: 60 minutos):
```bash
python cli.py monitor --intervalo 30
```
> Cada nova intimação encontrada dispara um alerta colorido no terminal, salva a certidão oficial em PDF na pasta `./certidoes/` e grava o registro no banco SQLite para evitar repetição.

Para rodar uma única varredura imediata (útil para cron jobs):
```bash
python cli.py monitor --uma-vez --dias 2
```

### 6. Baixar Certidão Oficial em PDF
```bash
python cli.py certidao <hash_da_comunicacao> -o certidao.pdf
```

### 7. Listar Todos os Tribunais Integrados ao CNJ
```bash
python cli.py tribunais
```

---

## 💻 Uso como Biblioteca em Código Python

```python
from client import ComunicaPJeClient

client = ComunicaPJeClient()

# 1. Busca simples
resposta = client.buscar_comunicacoes(
    numero_oab="123456",
    uf_oab="SP",
    itens_por_pagina=10
)

for comunicacao in resposta.items:
    print(f"Processo: {comunicacao.numeroprocessocommascara}")
    print(f"Tribunal: {comunicacao.siglaTribunal}")
    print(f"Texto: {comunicacao.texto_limpo[:150]}...")
    
# 2. Iterador automático com paginação transparente
for intimacao in client.iter_todas_comunicacoes(numero_oab="123456", uf_oab="SP", max_paginas=3):
    print(f"Intimação ID {intimacao.id} disponibilizada em {intimacao.data_disponibilizacao}")

# 3. Download da certidão oficial
if comunicacao.hash:
    client.baixar_certidao(comunicacao.hash, salvar_em="comprovante.pdf")
```
