"""Criptografia do Web Push sem dependência nova (só `cryptography` + `PyJWT`, já na imagem).

- RFC 8291 (Message Encryption for Web Push) com o content-coding `aes128gcm` (RFC 8188),
  um único registro;
- RFC 8292 (VAPID): JWT ES256 + cabeçalho ``Authorization: vapid t=..., k=...``.

Nada aqui loga chave privada nem segredo de inscrição.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Tamanho de registro anunciado no cabeçalho aes128gcm. Com um registro só, basta
# ser maior que o texto cifrado; 4096 é o que os navegadores e o RFC usam.
RECORD_SIZE = 4096
# Limite prático dos serviços de push (FCM/Mozilla/Apple aceitam ~4 KiB de corpo).
MAX_PLAINTEXT = RECORD_SIZE - 16 - 1 - 86  # tag GCM, delimitador, cabeçalho


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(data: str) -> bytes:
    data = data.strip()
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def public_key_bytes(public_key: ec.EllipticCurvePublicKey) -> bytes:
    """Ponto P-256 não comprimido (65 bytes, prefixo 0x04)."""
    return public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def private_key_from_bytes(raw: bytes) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def private_key_bytes(private_key: ec.EllipticCurvePrivateKey) -> bytes:
    return private_key.private_numbers().private_value.to_bytes(32, "big")


def public_key_from_bytes(raw: bytes) -> ec.EllipticCurvePublicKey:
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)


@dataclass(frozen=True)
class DerivedKeys:
    """Valores intermediários do RFC 8291 §3.4 (expostos para os testes com os vetores)."""

    ecdh_secret: bytes
    ikm: bytes
    prk: bytes
    cek: bytes
    nonce: bytes


def derive_keys(
    *,
    as_private: ec.EllipticCurvePrivateKey,
    ua_public: bytes,
    auth_secret: bytes,
    salt: bytes,
) -> DerivedKeys:
    ua_key = public_key_from_bytes(ua_public)
    as_public = public_key_bytes(as_private.public_key())
    ecdh_secret = as_private.exchange(ec.ECDH(), ua_key)
    # HKDF-Extract(auth_secret, ecdh_secret) + HKDF-Expand(key_info, 32)
    prk_key = _hmac_sha256(auth_secret, ecdh_secret)
    key_info = b"WebPush: info\x00" + ua_public + as_public
    ikm = _hmac_sha256(prk_key, key_info + b"\x01")
    # HKDF(salt, IKM) para CEK (16) e nonce (12)
    prk = _hmac_sha256(salt, ikm)
    cek = _hmac_sha256(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac_sha256(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    return DerivedKeys(ecdh_secret=ecdh_secret, ikm=ikm, prk=prk, cek=cek, nonce=nonce)


def encrypt(
    plaintext: bytes,
    *,
    ua_public: bytes,
    auth_secret: bytes,
    as_private: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
    record_size: int = RECORD_SIZE,
) -> bytes:
    """Cifra *plaintext* para uma inscrição (corpo HTTP com ``Content-Encoding: aes128gcm``).

    ``as_private``/``salt`` só são passados pelos testes (vetores do RFC); em uso real
    são sempre novos a cada mensagem.
    """
    if len(ua_public) != 65 or ua_public[0] != 0x04:
        raise ValueError("p256dh inválido (esperado ponto P-256 não comprimido de 65 bytes)")
    if len(auth_secret) != 16:
        raise ValueError("auth inválido (esperado 16 bytes)")
    if len(plaintext) > record_size - 16 - 1 - 86:
        raise ValueError("payload grande demais para um registro")
    as_private = as_private or ec.generate_private_key(ec.SECP256R1())
    salt = salt if salt is not None else os.urandom(16)
    keys = derive_keys(as_private=as_private, ua_public=ua_public, auth_secret=auth_secret, salt=salt)
    # Último (e único) registro: delimitador 0x02, sem padding extra.
    ciphertext = AESGCM(keys.cek).encrypt(keys.nonce, plaintext + b"\x02", None)
    as_public = public_key_bytes(as_private.public_key())
    header = salt + struct.pack("!IB", record_size, len(as_public)) + as_public
    return header + ciphertext


def decrypt(body: bytes, *, ua_private: ec.EllipticCurvePrivateKey, auth_secret: bytes) -> bytes:
    """Inverso de :func:`encrypt` (lado do navegador). Usado nos testes e no mock e2e."""
    salt = body[:16]
    _rs, idlen = struct.unpack("!IB", body[16:21])
    as_public = body[21 : 21 + idlen]
    ciphertext = body[21 + idlen :]
    ua_public = public_key_bytes(ua_private.public_key())
    ecdh_secret = ua_private.exchange(ec.ECDH(), public_key_from_bytes(as_public))
    prk_key = _hmac_sha256(auth_secret, ecdh_secret)
    ikm = _hmac_sha256(prk_key, b"WebPush: info\x00" + ua_public + as_public + b"\x01")
    prk = _hmac_sha256(salt, ikm)
    cek = _hmac_sha256(prk, b"Content-Encoding: aes128gcm\x00\x01")[:16]
    nonce = _hmac_sha256(prk, b"Content-Encoding: nonce\x00\x01")[:12]
    padded = AESGCM(cek).decrypt(nonce, ciphertext, None)
    stripped = padded.rstrip(b"\x00")
    if not stripped or stripped[-1] != 0x02:
        raise ValueError("delimitador de registro ausente")
    return stripped[:-1]


# ---------------------------------------------------------------------------
# VAPID (RFC 8292)
# ---------------------------------------------------------------------------

# Validade do JWT. O RFC exige no máximo 24 h; 12 h dá folga para relógio torto.
VAPID_TTL_SECONDS = 12 * 3600


def endpoint_audience(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    return f"{parts.scheme}://{parts.netloc}"


def vapid_jwt(private_key: ec.EllipticCurvePrivateKey, *, audience: str, subject: str, now: float | None = None) -> str:
    issued = int(now if now is not None else time.time())
    claims = {"aud": audience, "exp": issued + VAPID_TTL_SECONDS, "sub": subject}
    return jwt.encode(claims, private_key, algorithm="ES256", headers={"typ": "JWT"})


def vapid_authorization(
    private_key: ec.EllipticCurvePrivateKey, *, endpoint: str, subject: str, now: float | None = None
) -> str:
    token = vapid_jwt(private_key, audience=endpoint_audience(endpoint), subject=subject, now=now)
    k = b64url_encode(public_key_bytes(private_key.public_key()))
    return f"vapid t={token}, k={k}"
