import importlib.util
import subprocess
import sys
import time
from pathlib import Path

import jwt
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/mint_token.py"
spec = importlib.util.spec_from_file_location("mint_token", SCRIPT)
mint_token = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mint_token)

SECRET = "s" * 40


def test_token_verifies_with_a_standard_jwt_library_and_has_expected_claims():
    tok = mint_token.mint(SECRET, "acme", "alice", ["admin", "employee"], 600)
    claims = jwt.decode(tok, SECRET, algorithms=["HS256"])  # also checks exp
    assert claims["tenant_id"] == "acme" and claims["sub"] == "alice" and claims["roles"] == ["admin", "employee"]
    assert 590 <= claims["exp"] - int(time.time()) <= 600


def test_wrong_secret_and_expired_tokens_are_rejected():
    tok = mint_token.mint(SECRET, "acme", "a", [], 600)
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(tok, "x" * 40, algorithms=["HS256"])
    old = mint_token.mint(SECRET, "acme", "a", [], 60, now=int(time.time()) - 3600)
    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(old, SECRET, algorithms=["HS256"])


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(secret="short", tenant="acme", user="a", roles=[], ttl=60),
        dict(secret=SECRET, tenant="a b", user="a", roles=[], ttl=60),
        dict(secret=SECRET, tenant="acme", user="a", roles=["__system__"], ttl=60),
        dict(secret=SECRET, tenant="acme", user="a", roles=["bad role"], ttl=60),
        dict(secret=SECRET, tenant="acme", user="a", roles=[], ttl=0),
    ],
)
def test_invalid_input_is_refused(kwargs):
    with pytest.raises(ValueError):
        mint_token.mint(**kwargs)


def test_cli_prints_a_token_and_fails_without_secret():
    ok = subprocess.run([sys.executable, str(SCRIPT), "--tenant", "acme", "--user", "u", "--roles", "hr,employee"],
                        env={"JWT_SECRET": SECRET}, capture_output=True, text=True)
    assert ok.returncode == 0 and jwt.decode(ok.stdout.strip(), SECRET, algorithms=["HS256"])["roles"] == ["hr", "employee"]
    bad = subprocess.run([sys.executable, str(SCRIPT), "--tenant", "acme", "--user", "u"], env={}, capture_output=True, text=True)
    assert bad.returncode == 2 and "32 bytes" in bad.stderr
