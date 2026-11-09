#!/usr/bin/env python3
"""Mint an HS256 JWT the gateway will accept. Standard library only.

For deployments that do not use an OIDC provider (OIDC_ISSUER_URI unset): the operator mints tokens for
tenant users with the same JWT_SECRET the gateway runs with. Treat the secret and the tokens as credentials.

    JWT_SECRET=... python scripts/mint_token.py --tenant acme --user alice --roles admin,employee --ttl 86400
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time

TENANT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ROLE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
SYSTEM_ROLE = "__system__"  # reserved for the ingestion worker; never put in a user token


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def mint(secret: str, tenant: str, user: str, roles: list[str], ttl: int, now: int | None = None) -> str:
    if len(secret.encode()) < 32:
        raise ValueError("JWT_SECRET must be at least 32 bytes")
    if not TENANT_RE.match(tenant):
        raise ValueError("tenant must match [A-Za-z0-9_-]{1,64}")
    clean = [r for r in roles if ROLE_RE.match(r) and r != SYSTEM_ROLE]
    if len(clean) != len(roles):
        raise ValueError(f"invalid or reserved role in {roles!r}")
    if ttl <= 0:
        raise ValueError("ttl must be positive")
    now = int(time.time()) if now is None else now
    header = {"alg": "HS256", "typ": "JWT"}
    claims = {"sub": user, "tenant_id": tenant, "roles": clean, "iat": now, "exp": now + ttl}
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(claims, separators=(',', ':')).encode())}"
    sig = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(sig)}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tenant", required=True)
    p.add_argument("--user", required=True)
    p.add_argument("--roles", default="employee", help="comma-separated, e.g. admin,employee")
    p.add_argument("--ttl", type=int, default=3600, help="lifetime in seconds (default 3600)")
    args = p.parse_args()
    secret = os.environ.get("JWT_SECRET", "")
    try:
        print(mint(secret, args.tenant, args.user, [r for r in args.roles.split(",") if r], args.ttl))
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
