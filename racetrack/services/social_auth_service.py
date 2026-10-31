import base64
import json
import time

import requests
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa


APPLE_ISSUER = "https://appleid.apple.com"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}
_apple_key_cache = {"expires_at": 0, "keys": []}


class SocialAuthError(RuntimeError):
    pass


def _decode_segment(value):
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _jwt_parts(raw_token):
    try:
        encoded_header, encoded_payload, encoded_signature = raw_token.split(".")
        header = json.loads(_decode_segment(encoded_header))
        payload = json.loads(_decode_segment(encoded_payload))
        signature = _decode_segment(encoded_signature)
    except (AttributeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise SocialAuthError("The identity token is invalid.") from exc
    return header, payload, signature, f"{encoded_header}.{encoded_payload}".encode("ascii")


def _apple_keys():
    now = time.time()
    if _apple_key_cache["keys"] and _apple_key_cache["expires_at"] > now:
        return _apple_key_cache["keys"]
    try:
        response = requests.get("https://appleid.apple.com/auth/keys", timeout=8)
        response.raise_for_status()
        keys = response.json().get("keys") or []
    except (requests.RequestException, ValueError) as exc:
        raise SocialAuthError("Apple sign-in could not be verified right now.") from exc
    _apple_key_cache.update({"keys": keys, "expires_at": now + 6 * 60 * 60})
    return keys


def verify_apple_identity_token(raw_token, audience):
    header, claims, signature, signed_value = _jwt_parts(raw_token)
    if header.get("alg") != "RS256" or not header.get("kid"):
        raise SocialAuthError("The Apple identity token is invalid.")
    key = next((item for item in _apple_keys() if item.get("kid") == header["kid"]), None)
    if not key:
        _apple_key_cache.update({"keys": [], "expires_at": 0})
        key = next((item for item in _apple_keys() if item.get("kid") == header["kid"]), None)
    if not key:
        raise SocialAuthError("Apple's signing key is unavailable.")
    try:
        public_key = rsa.RSAPublicNumbers(
            int.from_bytes(_decode_segment(key["e"]), "big"),
            int.from_bytes(_decode_segment(key["n"]), "big"),
        ).public_key()
        public_key.verify(signature, signed_value, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, KeyError, ValueError, TypeError) as exc:
        raise SocialAuthError("The Apple identity token signature is invalid.") from exc
    if claims.get("iss") != APPLE_ISSUER or claims.get("aud") != audience:
        raise SocialAuthError("The Apple identity token was issued for another app.")
    if int(claims.get("exp") or 0) <= int(time.time()):
        raise SocialAuthError("The Apple identity token expired.")
    email = (claims.get("email") or "").strip().lower()
    if not claims.get("sub") or not email or claims.get("email_verified") not in (True, "true"):
        raise SocialAuthError("Apple did not provide a verified email address.")
    return {"subject": claims["sub"], "email": email}


def verify_google_identity_token(raw_token, audience):
    try:
        response = requests.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": raw_token},
            timeout=8,
        )
        response.raise_for_status()
        claims = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise SocialAuthError("Google sign-in could not be verified.") from exc
    if claims.get("aud") != audience or claims.get("iss") not in GOOGLE_ISSUERS:
        raise SocialAuthError("The Google identity token was issued for another app.")
    if int(claims.get("exp") or 0) <= int(time.time()):
        raise SocialAuthError("The Google identity token expired.")
    email = (claims.get("email") or "").strip().lower()
    if not claims.get("sub") or not email or claims.get("email_verified") not in (True, "true"):
        raise SocialAuthError("Google did not provide a verified email address.")
    return {
        "subject": claims["sub"],
        "email": email,
        "given_name": (claims.get("given_name") or "").strip(),
        "family_name": (claims.get("family_name") or "").strip(),
    }
