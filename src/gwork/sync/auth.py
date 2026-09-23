from __future__ import annotations

"""Get a short-lived access token from gog-cli credentials.

gog manages the full OAuth2 flow. REST calls outside gog's API coverage,
such as Docs API batchUpdate for content replacement, require an access token.
Build it from:
  - client_id / client_secret: ~/Library/Application Support/gogcli/credentials.json
  - refresh_token: temporarily exported with `gog auth tokens export`
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
    """Exchange the gog refresh token for a valid access token."""
    # Read client_id and client_secret from the gog config.
    if not GOG_CREDENTIALS.exists():
        raise FileNotFoundError(
            f"{GOG_CREDENTIALS} was not found. "
            "Ensure gog-cli is installed and authenticated."
        )
    creds = json.loads(GOG_CREDENTIALS.read_text())
    client_id = creds["client_id"]
    client_secret = creds["client_secret"]

    # Export the refresh token temporarily.
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

    # Exchange the refresh token for an access token.
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
        raise RuntimeError(f"OAuth2 did not return access_token: {result}")
    return result["access_token"]
