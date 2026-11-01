import io
import base64
import pyotp
import qrcode
import bcrypt
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
import secrets

# Utilitários de Hash de Senha com bcrypt
def gerar_hash_senha(senha: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(senha.encode("utf-8"), salt).decode("utf-8")


def verificar_hash_senha(senha: str, hash_armazenado: str) -> bool:
    try:
        return bcrypt.checkpw(senha.encode("utf-8"), hash_armazenado.encode("utf-8"))
    except Exception:
        return False


# Utilitários de 2FA (TOTP RFC 6238)
def gerar_secret_totp() -> str:
    """Gera um segredo Base32 para o Google Authenticator."""
    return pyotp.random_base32()


def gerar_uri_totp(email: str, secret: str, nome_emissor: str = "CAROL Monitor") -> str:
    """Gera a URI otpauth:// padrão para autenticadores."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=nome_emissor)


def gerar_qrcode_base64(totp_uri: str) -> str:
    """Converte a URI do TOTP em uma imagem QR Code PNG codificada em Base64."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=7,
        border=3,
    )
    qr.add_data(totp_uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{img_b64}"


def validar_codigo_totp(secret: str, codigo: str) -> bool:
    """
    Verifica o código de 6 dígitos informado pelo usuário.
    valid_window=1 permite uma tolerância de 30s antes/depois para compensar pequenos desvios de relógio.
    """
    if not secret or not codigo:
        return False
    totp = pyotp.TOTP(secret)
    # Remove espaços ou traços caso o usuário digite "123 456"
    cod_limpo = str(codigo).replace(" ", "").replace("-", "").strip()
    return totp.verify(cod_limpo, valid_window=1)


# Gerador de Tokens de Sessão Seguros
def gerar_token_sessao() -> str:
    return secrets.token_urlsafe(32)
