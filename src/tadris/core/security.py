import hashlib
import hmac
import os
import secrets

# Tests monkeypatch N to 2**4. Production uses 2**14.
N = 2**14
R = 8
P = 1
DKLEN = 32


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=N, r=R, p=P, dklen=DKLEN)
    return f"scrypt${N}${R}${P}${salt.hex()}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n_s, r_s, p_s, salt_hex, key_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(key_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def new_token() -> str:
    return secrets.token_hex(16)
