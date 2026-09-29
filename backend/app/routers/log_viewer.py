"""
Read-only tail of the API log file for controlled operations access.

Requires LOG_VIEWER_ENABLED=true, LOG_VIEWER_TOKEN, and LOG_FILE_PATH.
Keep disabled unless a deployment explicitly needs browser-accessible logs.

- GET /logs/recent — plain text snapshot (use /logs/watch for auto-refresh in the browser).
"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from app.core.config import get_settings
from app.core.limiter import limiter
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/logs", tags=["ops"])


def _tail_file(path: Path, max_lines: int, max_bytes: int = 512_000) -> str:
    if not path.is_file():
        return ""
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return ""
            read_size = min(max_bytes, size)
            f.seek(size - read_size)
            data = f.read().decode("utf-8", errors="replace")
    except OSError as e:
        logger.warning("log viewer read failed: %s", e)
        raise HTTPException(status_code=503, detail="Could not read log file") from e
    lines = data.splitlines()
    return "\n".join(lines[-max_lines:])


def _verify_log_viewer_token(token: str | None) -> None:
    settings = get_settings()
    if not settings.log_viewer_enabled or not settings.log_viewer_token:
        raise HTTPException(status_code=404, detail="Not found")
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if token != settings.log_viewer_token:
        raise HTTPException(status_code=401, detail="Unauthorized")


def _log_file_path():
    settings = get_settings()
    if not settings.log_file_path:
        raise HTTPException(
            status_code=503,
            detail="LOG_FILE_PATH is not set — enable file logging on the server.",
        )
    return Path(settings.log_file_path)


@router.get(
    "/recent",
    response_class=PlainTextResponse,
    summary="Tail of API log file (token + demo flag required)",
)
@limiter.limit("120/minute")
def recent_logs(
    request: Request,
    token: str = Query(..., description="Must match LOG_VIEWER_TOKEN"),
    lines: int = Query(200, ge=50, le=2000),
) -> str:
    _verify_log_viewer_token(token)
    settings = get_settings()
    path = _log_file_path()
    cap = min(lines, settings.log_viewer_max_lines)
    text = _tail_file(path, cap)
    if not text and not path.is_file():
        raise HTTPException(
            status_code=503,
            detail=f"Log file not found: {path}",
        )
    return text or "(log file empty)"


@router.get(
    "/watch",
    response_class=HTMLResponse,
    summary="HTML page that auto-refreshes log tail every few seconds",
)
@limiter.limit("30/minute")
def watch_logs(
    request: Request,
    token: str = Query(..., description="Must match LOG_VIEWER_TOKEN"),
    lines: int = Query(200, ge=50, le=2000),
    interval_ms: int = Query(4000, ge=2000, le=30000, description="Poll interval in ms"),
) -> HTMLResponse:
    """Single page: JS polls /api/logs/recent so judges do not need to mash F5."""
    _verify_log_viewer_token(token)
    settings = get_settings()
    if not settings.log_file_path:
        raise HTTPException(
            status_code=503,
            detail="LOG_FILE_PATH is not set — enable file logging on the server.",
        )
    cap = min(lines, settings.log_viewer_max_lines)
    token_js = json.dumps(token)
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>API logs (live)</title>
<style>
  body {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 0;
    background: #0d1117; color: #c9d1d9; }}
  #bar {{ padding: 10px 14px; background: #161b22; border-bottom: 1px solid #30363d;
    font-size: 0.85rem; }}
  #log {{ white-space: pre-wrap; padding: 12px 14px 48px; margin: 0; font-size: 0.8rem; }}
  #status {{ color: #58a6ff; }}
  .err {{ color: #f85149; }}
</style>
</head>
<body>
<div id="bar">Live tail · polling every <span id="iv"></span> · <span id="status">loading…</span></div>
<pre id="log"></pre>
<script>
const TOKEN = {token_js};
const LINES = {cap};
const pollMs = {interval_ms};
document.getElementById('iv').textContent = (pollMs / 1000) + 's';
async function poll() {{
  const el = document.getElementById('log');
  const st = document.getElementById('status');
  try {{
    const u = new URL('/api/logs/recent', window.location.origin);
    u.searchParams.set('token', TOKEN);
    u.searchParams.set('lines', String(LINES));
    const r = await fetch(u);
    if (!r.ok) {{
      st.innerHTML = '<span class="err">HTTP ' + r.status + '</span>';
      el.textContent = await r.text();
      return;
    }}
    st.textContent = 'OK · ' + new Date().toLocaleTimeString();
    el.textContent = await r.text();
    window.scrollTo(0, document.body.scrollHeight);
  }} catch (e) {{
    st.innerHTML = '<span class="err">' + e.message + '</span>';
  }}
}}
setInterval(poll, pollMs);
poll();
</script>
</body>
</html>"""
    )
