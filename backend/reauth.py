#!/usr/bin/env python3
"""
Re-authenticate and write a fresh token.json for the MCP server.

Run this whenever you see 'invalid_grant' errors:
  python backend/reauth.py

Root cause: Google OAuth apps in 'Testing' mode issue refresh tokens
that expire after 7 days. This script runs the OAuth flow again to
get a new one.
"""
import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from google_auth_oauthlib.flow import Flow

CREDENTIALS_PATH = Path(__file__).parent / "credentials.json"
TOKEN_PATH = Path(__file__).parent.parent / "token.json"
REDIRECT_URI = "http://localhost:8080"
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.readonly",
]

_auth_code: list[str] = []


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            _auth_code.append(params["code"][0])
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Auth successful! You can close this tab.</h1>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h1>Auth failed - no code received.</h1>")

    def log_message(self, *_):
        pass


def main():
    flow = Flow.from_client_secrets_file(
        str(CREDENTIALS_PATH),
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

    print("\nOpening browser for Google sign-in...")
    print(f"If the browser doesn't open automatically, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for callback on http://localhost:8501 ...")
    server = HTTPServer(("localhost", 8080), _CallbackHandler)
    server.handle_request()

    if not _auth_code:
        print("No auth code received. Exiting.")
        sys.exit(1)

    flow.fetch_token(code=_auth_code[0])
    creds = flow.credentials

    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes or SCOPES),
    }

    with open(TOKEN_PATH, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"\n✅  token.json refreshed → {TOKEN_PATH}")
    print("Restart Claude Desktop to pick up the new token.")


if __name__ == "__main__":
    main()
