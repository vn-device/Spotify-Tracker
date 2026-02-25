# Spotify Most Played (4 weeks)

A small terminal app that fetches your top tracks for the past four weeks (Spotify `short_term`) and displays/exports them.

Requirements

- Create a Spotify app at https://developer.spotify.com/dashboard and add `http://localhost:8080/callback` as a Redirect URI.
- Set the environment variable `SPOTIFY_CLIENT_ID` to your app's Client ID.

Configuration

- You can create a `.env` file in the project root with `SPOTIFY_CLIENT_ID=...` to avoid exporting env vars manually.
- Optionally set `SPOTIFY_TOKEN_PATH` to override where tokens are stored (defaults to `~/.spotify_most_played.json`).
 - You can create a `.env` file in the project root with `SPOTIFY_CLIENT_ID=...` to avoid exporting env vars manually.
 - See `.env.example` for a template you can copy.
 - Optionally set `SPOTIFY_TOKEN_PATH` to override where tokens are stored (defaults to `~/.spotify_most_played.json`).
 - If Spotify accepted a different local redirect (for example `http://127.0.0.1:8080/callback`), set `SPOTIFY_REDIRECT_URI` in your `.env` to that exact value. The script will default to `http://127.0.0.1:8080/callback`.

Install

```bash
python -m venv .venv
pip install -r requirements.txt
```

Platform-specific activation & run

- Windows (PowerShell):

```powershell
# activate
.venv\Scripts\Activate.ps1
# set env for this session (or create a .env)
$env:SPOTIFY_CLIENT_ID="your_client_id_here"
python spotify_most_played.py --limit 20
```

- macOS / Linux (bash/zsh):

```bash
# activate
.venv/bin/activate
# export env (or create a .env)
export SPOTIFY_CLIENT_ID=your_client_id_here
python spotify_most_played.py --limit 20
```

Notes

- This app uses Spotify's Authorization Code with PKCE flow. No client secret is required.
- Tokens are stored at the path in `SPOTIFY_TOKEN_PATH` or default `~/.spotify_most_played.json`.

Usage examples

- Top songs:

```bash
python spotify_most_played.py --songs --limit 10
```

- Top artists:

```bash
python spotify_most_played.py --artists --limit 10
```
