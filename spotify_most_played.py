import argparse
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_TOP_TRACKS = "https://api.spotify.com/v1/me/top/tracks"
REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8080/callback")
SCOPE = "user-top-read"

_default_token_path = os.environ.get("SPOTIFY_TOKEN_PATH", str(Path.home() / ".spotify_most_played.json"))
TOKEN_PATH = Path(_default_token_path).expanduser()

console = Console()


def generate_pkce_pair():
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


class OAuthHandler(BaseHTTPRequestHandler):
    server_version = "SpotifyPKCEServer/0.1"

    def do_GET(self):
        parsed = urlparse(self.path)
        expected_path = urlparse(REDIRECT_URI).path
        if parsed.path != expected_path:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
            return
        qs = parse_qs(parsed.query)
        self.server.auth_response = qs
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(b"<html><body><h1>Authentication complete.</h1><p>You can close this window.</p></body></html>")

    def log_message(self, format, *args):
        return


def start_local_server(timeout=120):
    server = HTTPServer(("", 8080), OAuthHandler)
    server.auth_response = None

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    start = time.time()
    while time.time() - start < timeout:
        if server.auth_response is not None:
            server.shutdown()
            return server.auth_response
        time.sleep(0.5)
    server.shutdown()
    return None


def request_user_authorization(client_id: str):
    code_verifier, code_challenge = generate_pkce_pair()
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge,
    }
    url = AUTH_URL + "?" + "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    webbrowser.open(url)
    console.print("Opened browser for Spotify authorization. If it didn't open, visit:")
    console.print(url)
    auth_resp = start_local_server()
    if not auth_resp or "code" not in auth_resp:
        raise RuntimeError("Failed to get authorization code (timeout or denied)")
    code = auth_resp["code"][0]
    return code, code_verifier


def exchange_code_for_token(code: str, code_verifier: str, client_id: str):
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "code_verifier": code_verifier,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=10)
    r.raise_for_status()
    return r.json()


def refresh_token(refresh_token: str, client_id: str):
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=10)
    r.raise_for_status()
    return r.json()


def save_tokens(obj: dict):
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps(obj))


def load_tokens():
    if not TOKEN_PATH.exists():
        return None
    try:
        return json.loads(TOKEN_PATH.read_text())
    except Exception:
        return None


def ensure_token(client_id: str):
    tokens = load_tokens()
    if tokens:
        # naive expiry handling
        if tokens.get("expires_at", 0) > time.time() + 60:
            return tokens
        if "refresh_token" in tokens:
            console.print("Refreshing access token...")
            new = refresh_token(tokens["refresh_token"], client_id)
            expires_in = new.get("expires_in", 3600)
            tokens.update(new)
            tokens["expires_at"] = time.time() + expires_in
            save_tokens(tokens)
            return tokens
    console.print("No valid token found; starting auth flow...")
    code, verifier = request_user_authorization(client_id)
    token_resp = exchange_code_for_token(code, verifier, client_id)
    expires_in = token_resp.get("expires_in", 3600)
    token_resp["expires_at"] = time.time() + expires_in
    save_tokens(token_resp)
    console.print(f"Saved tokens to: {TOKEN_PATH}")
    return token_resp


def fetch_top_tracks(access_token: str, limit: int = 50):
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"limit": min(limit, 50), "time_range": "short_term"}
    r = requests.get(API_TOP_TRACKS, headers=headers, params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("items", [])


def display_tracks(tracks):
    table = Table(title="Top Tracks — Past 4 Weeks")
    table.add_column("#", style="bold")
    table.add_column("Title")
    table.add_column("Artists")
    table.add_column("Album")
    table.add_column("Duration")
    for i, t in enumerate(tracks, 1):
        name = t.get("name")
        artists = ", ".join(a.get("name") for a in t.get("artists", []))
        album = t.get("album", {}).get("name", "")
        dur_ms = t.get("duration_ms", 0)
        dur = f"{int(dur_ms/60000)}:{int(dur_ms/1000)%60:02d}"
        table.add_row(str(i), name, artists, album, dur)
    console.print(table)


def export_csv(tracks, out_path: Path):
    import csv

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["rank", "title", "artists", "album", "duration_ms", "spotify_url"])
        for i, t in enumerate(tracks, 1):
            url = t.get("external_urls", {}).get("spotify", "")
            artists = ", ".join(a.get("name") for a in t.get("artists", []))
            w.writerow([i, t.get("name"), artists, t.get("album", {}).get("name", ""), t.get("duration_ms", 0), url])
    console.print(f"Exported CSV to {out_path}")


def main():
    p = argparse.ArgumentParser(description="Spotify — Most Played Past 4 Weeks")
    p.add_argument("--limit", type=int, default=20, help="Number of tracks to show (max 50)")
    p.add_argument("--export", type=str, help="Export results to CSV file path")
    args = p.parse_args()

    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    if not client_id:
        console.print("Please set the SPOTIFY_CLIENT_ID environment variable and register the redirect URI.")
        raise SystemExit(1)

    tokens = ensure_token(client_id)
    tracks = fetch_top_tracks(tokens.get("access_token"), limit=args.limit)
    display_tracks(tracks)
    if args.export:
        export_csv(tracks, Path(args.export))


if __name__ == "__main__":
    main()
