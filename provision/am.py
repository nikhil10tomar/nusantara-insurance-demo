#!/usr/bin/env python3
"""Nusantara demo identities in AM. Idempotent."""
from __future__ import annotations

import sys
import time

from _http import HttpError, basic, call, items, jwt_claims

AM = "http://localhost:8093"
AM_GW = "http://localhost:8092"
DOMAIN_HRID = "gamma"
ORG_ENV = f"{AM}/management/organizations/DEFAULT/environments/DEFAULT"
TOKEN_EXCHANGE = "urn:ietf:params:oauth:grant-type:token-exchange"
PASSWORD = "NusantaraDemo#2026"

USERS = [
    ("siti.claims", "Siti", "Rahayu", "siti.rahayu@nusantara.demo"),
    ("agus.dev", "Agus", "Wijaya", "agus.dev@nusantara.demo"),
    ("budi.ops", "Budi", "Santoso", "budi.ops@nusantara.demo"),
]

APPS = [
    ("Nusantara Control Tower", "nusantara-control-tower", "nusantara-control-tower-secret", "WEB",
     ["password", "refresh_token"]),
    ("Nusantara Staff Agent", "nusantara-staff-agent", "nusantara-staff-agent-secret", "SERVICE",
     ["client_credentials", TOKEN_EXCHANGE]),
    ("Nusantara Dev Agent", "nusantara-dev-agent", "nusantara-dev-agent-secret", "SERVICE",
     ["client_credentials", TOKEN_EXCHANGE]),
]


def token() -> str:
    return call("POST", f"{AM}/management/auth/token", auth=basic("admin", "adminadmin"))["access_token"]


def main() -> None:
    bearer = "Bearer " + token()

    def am(method: str, path: str, body=None):
        return call(method, f"{ORG_ENV}{path}", body, auth=bearer)

    domain = next((d for d in items(am("GET", "/domains?size=200")) if d.get("hrid") == DOMAIN_HRID), None)
    if not domain:
        sys.exit(f"AM domain '{DOMAIN_HRID}' not found — run Gamma SDK setup first")
    dom = f"/domains/{domain['id']}"
    print(f"AM domain {DOMAIN_HRID}")

    am("PATCH", dom, {"tokenExchangeSettings": {
        "enabled": True,
        "allowedSubjectTokenTypes": ["urn:ietf:params:oauth:token-type:access_token"],
        "allowedRequestedTokenTypes": ["urn:ietf:params:oauth:token-type:access_token"],
        "allowedActorTokenTypes": ["urn:ietf:params:oauth:token-type:access_token"],
        "allowImpersonation": True,
        "allowDelegation": True,
        "maxDelegationDepth": 5,
    }})
    print("  token exchange enabled")

    idp = items(am("GET", f"{dom}/identities"))[0]["id"]
    existing_users = {u.get("username"): u for u in items(am("GET", f"{dom}/users?size=200"))}
    for username, first, last, email in USERS:
        if existing_users.get(username):
            print(f"  = user {username}")
        else:
            am("POST", f"{dom}/users", {
                "username": username, "password": PASSWORD, "email": email,
                "firstName": first, "lastName": last, "preRegistration": False, "source": idp,
            })
            print(f"  + user {username}")

    scopes = {s["key"]: s for s in items(am("GET", f"{dom}/scopes?size=200"))}
    for key, name in (("claims:read", "Claims (read)"), ("code:read", "Code repository (read)")):
        if key not in scopes:
            am("POST", f"{dom}/scopes", {"key": key, "name": name, "description": name})
            print(f"  + scope {key}")

    apps = {a["name"]: a for a in items(am("GET", f"{dom}/applications?size=200"))}
    for name, cid, secret, typ, grants in APPS:
        app = apps.get(name)
        if not app:
            body = {"name": name, "type": typ, "clientId": cid, "clientSecret": secret}
            if typ == "WEB":
                body["redirectUris"] = ["http://localhost:8830/callback"]
            app = am("POST", f"{dom}/applications", body)
            print(f"  + app {name}")
        else:
            print(f"  = app {name}")
        is_human = typ == "WEB"
        scope_settings = [
            {"scope": s, "defaultScope": is_human}
            for s in ("openid", "profile", "email", "claims:read", "code:read")
        ]
        oauth = {
            "grantTypes": grants,
            "tokenEndpointAuthMethod": "client_secret_post",
            "accessTokenValiditySeconds": 7200,
            "scopeSettings": scope_settings,
            "enhanceScopesWithUserPermissions": is_human,
            "tokenCustomClaims": [
                {"tokenType": "ACCESS_TOKEN", "claimName": "preferred_username",
                 "claimValue": "{#context.attributes['user']['username']}"},
                {"tokenType": "ACCESS_TOKEN", "claimName": "email",
                 "claimValue": "{#context.attributes['user']['email']}"},
            ],
        }
        patch = {"settings": {"oauth": oauth}}
        if is_human:
            patch["identityProviders"] = [{"identity": idp, "priority": 0}]
        am("PATCH", f"{dom}/applications/{app['id']}", patch)

    verify()


def tok(form: dict, *, attempts: int = 5) -> dict:
    url = f"{AM_GW}/{DOMAIN_HRID}/oauth/token"
    last: HttpError | None = None
    for i in range(attempts):
        try:
            return call("POST", url, form=form)
        except HttpError as e:
            last = e
            if e.code in (404, 500, 502, 503) and i + 1 < attempts:
                time.sleep(0.8 * (i + 1))
                continue
            raise
    raise last  # type: ignore[misc]


def verify() -> None:
    print("\nVerify OBO (staff path):")
    try:
        user = tok({
            "grant_type": "password",
            "username": "siti.claims",
            "password": PASSWORD,
            "client_id": "nusantara-control-tower",
            "client_secret": "nusantara-control-tower-secret",
            "scope": "openid profile email claims:read",
        })["access_token"]
        actor = tok({
            "grant_type": "client_credentials",
            "client_id": "nusantara-staff-agent",
            "client_secret": "nusantara-staff-agent-secret",
            "scope": "profile email claims:read",
        })["access_token"]
        exchanged = tok({
            "grant_type": TOKEN_EXCHANGE,
            "client_id": "nusantara-staff-agent",
            "client_secret": "nusantara-staff-agent-secret",
            "subject_token": user,
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "actor_token": actor,
            "actor_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "scope": "profile email claims:read",
        })["access_token"]
        ec = jwt_claims(exchanged)
        print(f"  OK sub={ec.get('preferred_username')} act={(ec.get('act') or {}).get('sub')}")
    except HttpError as e:
        print(f"  WARN: {e.code} {e.body[:180]}")


if __name__ == "__main__":
    main()
