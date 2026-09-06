from __future__ import annotations

"""Obtiene un access token de corta duración usando las credenciales de gog-cli.

gog gestiona el OAuth2 completo. Para las llamadas REST que gog no cubre
(ej. Docs API batchUpdate para reemplazar contenido), necesitamos un access
token. Lo construimos con:
  - client_id / client_secret: ~/Library/Application Support/gogcli/credentials.json
  - refresh_token: exportado temporalmente con `gog auth tokens export`
"""

import json
import os
import subprocess
import tempfile
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional


GOG_CONFIG_DIR = Path.home() / "Library" / "Application Support" / "gogcli"
GOG_CREDENTIALS = GOG_CONFIG_DIR / "credentials.json"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def get_access_token(account: str) -> str:
    """Devuelve un access token válido intercambiando el refresh token de gog."""
    # Leer client_id y client_secret del config de gog
    if not GOG_CREDENTIALS.exists():
        raise FileNotFoundError(
            f"No se encontró {GOG_CREDENTIALS}. "
            "Asegúrate de tener gog-cli instalado y autenticado."
        )
    creds = json.loads(GOG_CREDENTIALS.read_text())
    client_id = creds["client_id"]
    client_secret = creds["client_secret"]

    # Exportar refresh token temporalmente
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        subprocess.run(
            ["gog", "auth", "tokens", "export", account, "--out", tmp, "--overwrite"],
            capture_output=True, text=True, check=True,
        )
        token_data = json.loads(Path(tmp).read_text())
        refresh_token = token_data["refresh_token"]
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass

    # Intercambiar refresh token por access token
    payload = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_ENDPOINT, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    if "access_token" not in result:
        raise RuntimeError(f"OAuth2 no devolvió access_token: {result}")
    return result["access_token"]
