import pyotp
from auth import (
    gerar_hash_senha,
    verificar_hash_senha,
    gerar_secret_totp,
    gerar_uri_totp,
    gerar_qrcode_base64,
    validar_codigo_totp,
    gerar_token_sessao
)


def test_hash_e_verificacao_senha():
    senha = "MinhaSenhaForte@2026"
    hash_senha = gerar_hash_senha(senha)

    assert hash_senha != senha
    assert hash_senha.startswith("$2b$") or hash_senha.startswith("$2a$")

    # Senha correta deve validar
    assert verificar_hash_senha(senha, hash_senha) is True

    # Senha incorreta deve falhar
    assert verificar_hash_senha("SenhaErrada", hash_senha) is False


def test_geracao_secret_totp():
    secret = gerar_secret_totp()
    assert isinstance(secret, str)
    assert len(secret) == 32
    # Base32 só contém A-Z e 2-7
    assert secret.isalnum()


def test_geracao_uri_e_qrcode():
    secret = gerar_secret_totp()
    email = "usuario@empresa.com"
    uri = gerar_uri_totp(email, secret, nome_emissor="CAROL Teste")

    assert uri.startswith("otpauth://totp/")
    assert "usuario%40empresa.com" in uri or "usuario@empresa.com" in uri
    assert secret in uri

    qr_b64 = gerar_qrcode_base64(uri)
    assert qr_b64.startswith("data:image/png;base64,")
    assert len(qr_b64) > 200


def test_validacao_codigo_totp():
    secret = gerar_secret_totp()
    totp = pyotp.TOTP(secret)
    codigo_atual = totp.now()

    # Código atual válido
    assert validar_codigo_totp(secret, codigo_atual) is True

    # Código com espaço ou formatação
    codigo_formatado = f"{codigo_atual[:3]} {codigo_atual[3:]}"
    assert validar_codigo_totp(secret, codigo_formatado) is True

    # Código incorreto
    assert validar_codigo_totp(secret, "000000") is False

    # Secret vazio ou código vazio
    assert validar_codigo_totp("", codigo_atual) is False
    assert validar_codigo_totp(secret, "") is False


def test_gerador_token_sessao():
    t1 = gerar_token_sessao()
    t2 = gerar_token_sessao()
    assert len(t1) >= 32
    assert t1 != t2
