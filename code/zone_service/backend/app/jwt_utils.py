"""Ma hoa / xac thuc JWT khong can thu vien ngoai cho HS256.

RS256 (khoa cong khai cua Backend) duoc ho tro neu cai them PyJWT + cryptography.
"""

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional


class JwtError(Exception):
    pass


def encode_hs256(claims: Dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = "{}.{}".format(_b64(json.dumps(header, separators=(",", ":"))), _b64(json.dumps(claims, separators=(",", ":"))))
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    return "{}.{}".format(signing_input, _b64(signature))


def decode(
    token: str,
    algorithm: str,
    secret: Optional[str] = None,
    public_key: Optional[str] = None,
    issuer: Optional[str] = None,
    audience: Optional[str] = None,
    leeway_seconds: int = 30,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    algorithm = (algorithm or "HS256").upper()
    if algorithm == "HS256":
        claims = _decode_hs256(token, secret or "")
    elif algorithm in ("RS256", "ES256"):
        claims = _decode_with_pyjwt(token, algorithm, public_key)
    else:
        raise JwtError("Unsupported JWT algorithm {}".format(algorithm))

    current = time.time() if now is None else now
    if "exp" in claims and current > float(claims["exp"]) + leeway_seconds:
        raise JwtError("Token expired")
    if "nbf" in claims and current + leeway_seconds < float(claims["nbf"]):
        raise JwtError("Token not yet valid")
    if issuer and claims.get("iss") != issuer:
        raise JwtError("Invalid issuer")
    if audience:
        aud = claims.get("aud")
        audiences = aud if isinstance(aud, list) else [aud]
        if audience not in audiences:
            raise JwtError("Invalid audience")
    return claims


def _decode_hs256(token: str, secret: str) -> Dict[str, Any]:
    if not secret:
        raise JwtError("JWT secret is not configured")
    parts = token.split(".")
    if len(parts) != 3:
        raise JwtError("Malformed token")
    header = _json(parts[0])
    if str(header.get("alg", "")).upper() != "HS256":
        raise JwtError("Unexpected token algorithm")
    expected = hmac.new(secret.encode("utf-8"), "{}.{}".format(parts[0], parts[1]).encode("ascii"), hashlib.sha256).digest()
    if not hmac.compare_digest(expected, _unb64(parts[2])):
        raise JwtError("Invalid signature")
    return _json(parts[1])


def _decode_with_pyjwt(token: str, algorithm: str, public_key: Optional[str]) -> Dict[str, Any]:
    if not public_key:
        raise JwtError("JWT public key is not configured")
    try:
        import jwt  # PyJWT
    except ImportError as exc:  # pragma: no cover - phu thuoc moi truong
        raise JwtError("RS256 requires PyJWT[crypto]") from exc
    try:
        return jwt.decode(token, public_key, algorithms=[algorithm], options={"verify_exp": False, "verify_aud": False})
    except Exception as exc:  # pragma: no cover
        raise JwtError(str(exc)) from exc


def _b64(value) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise JwtError("Malformed token") from exc


def _json(segment: str) -> Dict[str, Any]:
    try:
        value = json.loads(_unb64(segment).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise JwtError("Malformed token") from exc
    if not isinstance(value, dict):
        raise JwtError("Malformed token")
    return value
