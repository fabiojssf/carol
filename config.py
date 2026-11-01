import os
from pathlib import Path
from dotenv import load_dotenv

# Carrega variáveis do arquivo .env se existir
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# --- Configurações de Rede e Base URL ---
# URL base pública do sistema (ex: https://carol.suaempresa.com.br)
BASE_URL = os.getenv("BASE_URL") or os.getenv("CAROL_BASE_URL") or "http://localhost:8000"
BASE_URL = BASE_URL.rstrip("/")

# --- Configurações de Banco de Dados ---
# Suporte a DATABASE_URL ou variáveis separadas do PostgreSQL
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    pg_user = os.getenv("POSTGRES_USER")
    pg_pass = os.getenv("POSTGRES_PASSWORD")
    pg_host = os.getenv("POSTGRES_HOST")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    pg_db = os.getenv("POSTGRES_DB")

    if pg_user and pg_host and pg_db:
        auth_part = f"{pg_user}:{pg_pass}@" if pg_pass else f"{pg_user}@"
        DATABASE_URL = f"postgresql://{auth_part}{pg_host}:{pg_port}/{pg_db}"

# Fallback para SQLite se nenhuma variável do PostgreSQL for fornecida
SQLITE_DB_PATH = os.getenv("CAROL_DB_PATH", "carol_data.sqlite")

# --- Diretórios do Sistema ---
CERTIDOES_DIR = os.getenv("CAROL_CERTIDOES_DIR", "./certidoes")
WEBHOOK_GLOBAL_URL = os.getenv("CAROL_WEBHOOK_URL")
