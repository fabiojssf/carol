import pytest
import tempfile
import os
from pathlib import Path
from fastapi.testclient import TestClient

from storage import CarolStorage
from notifier import CarolNotifier
from monitor import CarolMonitor
import server


@pytest.fixture(scope="function")
def test_storage(tmp_path):
    """Cria uma instância isolada do banco SQLite em diretório temporário para cada teste."""
    db_file = tmp_path / "test_carol.sqlite"
    storage_inst = CarolStorage(database_url=None, sqlite_path=db_file)
    return storage_inst


@pytest.fixture(scope="function")
def client(test_storage, monkeypatch):
    """Cliente de teste do FastAPI configurado com o banco isolado."""
    # Substitui a instância de storage e notifier no server para isolamento
    monkeypatch.setattr(server, "storage", test_storage)
    test_notifier = CarolNotifier(storage=test_storage, base_url="https://carol.test.com")
    monkeypatch.setattr(server, "notifier", test_notifier)
    test_motor = CarolMonitor(storage=test_storage, notifier=test_notifier)
    monkeypatch.setattr(server, "motor", test_motor)

    with TestClient(server.app) as test_client:
        yield test_client


@pytest.fixture(scope="function")
def admin_client(client, test_storage):
    """Cliente autenticado como Administrador."""
    # Garante a existência do usuário admin no banco isolado
    if not test_storage.obter_usuario_por_email("admin@carol.com"):
        test_storage.cadastrar_usuario("Administrador", "admin@carol.com", "admin123", "admin", True)
    res = client.post("/api/auth/login", json={"email": "admin@carol.com", "senha": "admin123"})
    assert res.status_code == 200, f"Falha no login do admin: {res.text}"
    return client


@pytest.fixture(scope="function")
def operador_client(client, test_storage):
    """Cliente autenticado como Operador."""
    # Garante que um admin existe para que o próximo seja operador
    if not test_storage.obter_usuario_por_email("admin@carol.com"):
        test_storage.cadastrar_usuario("Administrador", "admin@carol.com", "admin123", "admin", True)

    # Cria usuário operador no banco
    test_storage.cadastrar_usuario(
        nome="Operador Teste",
        email="operador@carol.com",
        senha="senha123",
        perfil="operador",
        ativo=True
    )
    res = client.post("/api/auth/login", json={"email": "operador@carol.com", "senha": "senha123"})
    assert res.status_code == 200, f"Falha no login do operador: {res.text}"
    return client
