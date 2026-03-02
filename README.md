# Spotify Most Played

An interactive terminal app that fetches your top tracks and artists across various time ranges and displays them in the terminal or exports an HTML report to your web browser.

## Requirements

- Create a Spotify app at https://developer.spotify.com/dashboard and add `http://localhost:8080/callback` as a Redirect URI.
- Set the environment variable `SPOTIFY_CLIENT_ID` to your app's Client ID.

## Configuration

- You can create a `.env` file in the project root with `SPOTIFY_CLIENT_ID=...` to avoid exporting env vars manually.
- See `.env.example` for a template you can copy.
- Optionally set `SPOTIFY_TOKEN_PATH` to override where tokens are stored (defaults to `~/.spotify_most_played.json`).
- If Spotify accepted a different local redirect (for example `http://127.0.0.1:8080/callback`), set `SPOTIFY_REDIRECT_URI` in your `.env` to that exact value. The script will default to `http://127.0.0.1:8080/callback`.

## Install

```bash
python -m venv .venv
pip install -r requirements.txt
```

## Platform-Specific Activation & Run

# Windows
```.venv\Scripts\Activate.ps1
Note: set env for this session (or rely on .env file)
$env:SPOTIFY_CLIENT_ID="your_client_id_here"
python spotify_most_played.py
```

# Linux / macOS
```.venv/bin/activate
Note: export env for this session (or rely on .env file)
export SPOTIFY_CLIENT_ID="your_client_id_here"
python spotify_most_played.py
```
