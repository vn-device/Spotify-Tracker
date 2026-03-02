import base64
import hashlib
import json
import os
import secrets
import tempfile
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
from rich.prompt import Prompt, IntPrompt, Confirm

load_dotenv()

# Real Spotify Web API Endpoints
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_TOP_TRACKS = "https://api.spotify.com/v1/me/top/tracks"
API_TOP_ARTISTS = "https://api.spotify.com/v1/me/top/artists"
REDIRECT_URI = os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8080/callback")
SCOPE = "user-top-read"

_default_token_path = os.environ.get("SPOTIFY_TOKEN_PATH", str(Path.home() / ".spotify_most_played.json"))
TOKEN_PATH = Path(_default_token_path).expanduser()

console = Console()

TIME_RANGE_MAP = {
    "short": {"api": "short_term", "label": "Past 4 Weeks"},
    "medium": {"api": "medium_term", "label": "Past 6 Months"},
    "long": {"api": "long_term", "label": "All Time"},
}


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


def fetch_top_tracks(access_token: str, limit: int = 50, time_range: str = "short_term"):
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"limit": min(limit, 50), "time_range": time_range}
    r = requests.get(API_TOP_TRACKS, headers=headers, params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("items", [])


def fetch_top_artists(access_token: str, limit: int = 50, time_range: str = "short_term"):
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"limit": min(limit, 50), "time_range": time_range}
    r = requests.get(API_TOP_ARTISTS, headers=headers, params=params, timeout=10)
    r.raise_for_status()
    return r.json().get("items", [])


def display_tracks_terminal(tracks, time_label: str):
    table = Table(title=f"Top Tracks — {time_label}", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Title", style="bold green")
    table.add_column("Artists", style="cyan")
    table.add_column("Album", style="italic yellow")
    table.add_column("Duration", justify="right")
    
    for i, t in enumerate(tracks, 1):
        name = t.get("name", "Unknown")
        url = t.get("external_urls", {}).get("spotify", "")
        
        name_display = f"[link={url}]{name}[/link]" if url else name
        
        artists = ", ".join(a.get("name") for a in t.get("artists", []))
        album = t.get("album", {}).get("name", "")
        
        dur_ms = t.get("duration_ms", 0)
        dur = f"{int(dur_ms/60000)}:{int(dur_ms/1000)%60:02d}"
        
        table.add_row(str(i), name_display, artists, album, dur)
        
    console.print(table)


def display_artists_terminal(artists, tracks, time_label: str):
    # Cross-reference user's top tracks to find highest ranked song per artist
    top_track_map = {}
    for t in tracks:
        track_name = t.get("name", "Unknown")
        for artist in t.get("artists", []):
            artist_name = artist.get("name")
            if artist_name and artist_name not in top_track_map:
                top_track_map[artist_name] = track_name

    table = Table(title=f"Top Artists — {time_label}", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Name", style="bold green")
    table.add_column("Your Top Song", style="italic yellow")
    
    for i, a in enumerate(artists, 1):
        name = a.get("name", "Unknown")
        url = a.get("external_urls", {}).get("spotify", "")
        
        name_display = f"[link={url}]{name}[/link]" if url else name
        top_song = top_track_map.get(name, "N/A")
        
        table.add_row(str(i), name_display, top_song)
        
    console.print(table)


def cleanup_temp_file(path: str, delay_seconds: int = 3):
    time.sleep(delay_seconds)
    try:
        os.unlink(path)
    except OSError as e:
        console.print(f"[dim red]Failed to delete temp file {path}: {e}[/dim red]")


def display_in_browser(data, item_type, time_label: str, cross_ref_tracks=None):
    html_template = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Spotify Top Stats</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #121212; color: #ffffff; padding: 40px; }}
            h1 {{ color: #1DB954; margin-bottom: 5px; }}
            h3 {{ color: #b3b3b3; margin-top: 0; margin-bottom: 25px; font-weight: normal; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 12px; border-bottom: 1px solid #282828; text-align: left; vertical-align: middle; }}
            th {{ text-transform: uppercase; font-size: 12px; color: #b3b3b3; letter-spacing: 1px; }}
            a {{ color: #ffffff; text-decoration: none; font-weight: bold; }}
            a:hover {{ color: #1DB954; text-decoration: underline; }}
            .subtext {{ color: #b3b3b3; font-size: 14px; text-transform: capitalize; }}
            .thumb-artist {{ width: 48px; height: 48px; border-radius: 50%; object-fit: cover; display: block; }}
            .thumb-track {{ width: 48px; height: 48px; border-radius: 4px; object-fit: cover; display: block; }}
            .img-cell {{ width: 60px; text-align: center; }}
        </style>
    </head>
    <body>
        <h1>Your Top {title}</h1>
        <h3>{time_label}</h3>
        <table>
            {headers}
            {rows}
        </table>
    </body>
    </html>
    """
    
    headers = ""
    rows = ""
    
    if item_type == "artists":
        top_track_map = {}
        if cross_ref_tracks:
            for t in cross_ref_tracks:
                track_name = t.get("name", "Unknown")
                for artist in t.get("artists", []):
                    artist_name = artist.get("name")
                    if artist_name and artist_name not in top_track_map:
                        top_track_map[artist_name] = track_name

        headers = "<tr><th>#</th><th class='img-cell'></th><th>Artist</th><th>Your Top Song</th></tr>"
        for i, a in enumerate(data, 1):
            name = a.get("name", "Unknown")
            url = a.get("external_urls", {}).get("spotify", "#")
            
            top_song = top_track_map.get(name, "N/A")
            
            images = a.get("images", [])
            image_url = images[-1].get("url", "") if images else ""
            img_tag = f'<img src="{image_url}" class="thumb-artist" alt="{name}">' if image_url else ""
            
            rows += f"""
                <tr>
                    <td>{i}</td>
                    <td class="img-cell">{img_tag}</td>
                    <td><a href="{url}" target="_blank">{name}</a></td>
                    <td class="subtext">{top_song}</td>
                </tr>
            """
    else:
        headers = "<tr><th>#</th><th class='img-cell'></th><th>Title</th><th>Artists</th><th>Album</th><th>Duration</th></tr>"
        for i, t in enumerate(data, 1):
            name = t.get("name", "Unknown")
            url = t.get("external_urls", {}).get("spotify", "#")
            artists = ", ".join(a.get("name") for a in t.get("artists", []))
            album = t.get("album", {}).get("name", "")
            dur_ms = t.get("duration_ms", 0)
            dur = f"{int(dur_ms/60000)}:{int(dur_ms/1000)%60:02d}"
            
            images = t.get("album", {}).get("images", [])
            image_url = images[-1].get("url", "") if images else ""
            img_tag = f'<img src="{image_url}" class="thumb-track" alt="{album}">' if image_url else ""
            
            rows += f"""
                <tr>
                    <td>{i}</td>
                    <td class="img-cell">{img_tag}</td>
                    <td><a href="{url}" target="_blank">{name}</a></td>
                    <td class="subtext">{artists}</td>
                    <td class="subtext">{album}</td>
                    <td class="subtext">{dur}</td>
                </tr>
            """

    final_html = html_template.format(
        title="Artists" if item_type == "artists" else "Tracks",
        time_label=time_label,
        headers=headers,
        rows=rows
    )

    fd, path = tempfile.mkstemp(suffix=".html", prefix="spotify_stats_")
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(final_html)
    
    webbrowser.open(f"file://{path}")
    console.print(f"Opened report in your web browser. Cleaning up temporary files...")

    threading.Thread(target=cleanup_temp_file, args=(path, 3)).start()


def main():
    client_id = os.environ.get("SPOTIFY_CLIENT_ID")
    if not client_id:
        console.print("[bold red]Error:[/bold red] Please set the SPOTIFY_CLIENT_ID environment variable and register the redirect URI.")
        raise SystemExit(1)

    item_type = Prompt.ask(
        "What would you like to view?", 
        choices=["artists", "songs"], 
        default="artists"
    )
    
    time_choice = Prompt.ask(
        "Select a time range (short=4 weeks, medium=6 months, long=all time)", 
        choices=["short", "medium", "long"], 
        default="short"
    )
    
    limit = IntPrompt.ask("How many items to show? (1-50)", default=10)
    limit = max(1, min(limit, 50))
    
    display_browser = Confirm.ask("Display results in a web browser?")

    time_config = TIME_RANGE_MAP[time_choice]
    api_time_range = time_config["api"]
    time_label = time_config["label"]

    tokens = ensure_token(client_id)
    
    if item_type == "artists":
        artists = fetch_top_artists(tokens.get("access_token"), limit=limit, time_range=api_time_range)
        # Fetch max tracks strictly for the mapping algorithm
        tracks_for_mapping = fetch_top_tracks(tokens.get("access_token"), limit=50, time_range=api_time_range)
        
        if display_browser:
            display_in_browser(artists, "artists", time_label, cross_ref_tracks=tracks_for_mapping)
        else:
            display_artists_terminal(artists, tracks_for_mapping, time_label)
    else:
        tracks = fetch_top_tracks(tokens.get("access_token"), limit=limit, time_range=api_time_range)
        if display_browser:
            display_in_browser(tracks, "songs", time_label)
        else:
            display_tracks_terminal(tracks, time_label)


if __name__ == "__main__":
    main()