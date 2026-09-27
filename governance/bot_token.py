"""Fetch the OpenMetadata ingestion-bot JWT and store it in .env as OPENMETADATA_JWT_TOKEN.

Uses the default local admin (admin@open-metadata.org / admin) of a fresh docker install.
The bot token (not a login session, which expires after an hour) is what headless
ingestion, the MCP clients and the agents use.
"""

import base64
import os
import pathlib
import re

import requests

HOST = os.environ.get("OPENMETADATA_HOST", "http://localhost:8585/api").rstrip("/")
ADMIN_EMAIL = os.environ.get("OPENMETADATA_ADMIN_EMAIL", "admin@open-metadata.org")
ADMIN_PASSWORD = os.environ.get("OPENMETADATA_ADMIN_PASSWORD", "admin")
ENV_FILE = pathlib.Path(".env")


def main() -> None:
    login = requests.post(
        f"{HOST}/v1/users/login",
        json={"email": ADMIN_EMAIL, "password": base64.b64encode(ADMIN_PASSWORD.encode()).decode()},
        timeout=30,
    )
    login.raise_for_status()
    headers = {"Authorization": f"Bearer {login.json()['accessToken']}"}
    bot = requests.get(f"{HOST}/v1/bots/name/ingestion-bot", headers=headers, timeout=30).json()
    auth = requests.get(
        f"{HOST}/v1/users/auth-mechanism/{bot['botUser']['id']}", headers=headers, timeout=30
    ).json()
    token = auth["config"]["JWTToken"]

    if not ENV_FILE.exists():
        ENV_FILE.write_text(pathlib.Path(".env.example").read_text())
    text = ENV_FILE.read_text()
    text = re.sub(r"^OPENMETADATA_JWT_TOKEN=.*$", f"OPENMETADATA_JWT_TOKEN={token}", text, flags=re.M)
    ENV_FILE.write_text(text)
    print("OPENMETADATA_JWT_TOKEN written to .env")


if __name__ == "__main__":
    main()
