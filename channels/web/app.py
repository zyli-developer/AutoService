"""
AutoService Web Server — thin FastAPI entry point.

Routes:
  GET  /           -> redirect to /login
  GET  /login      -> login.html (access-code login)
  GET  /chat       -> chat.html (if exists, served by plugin static)

  GET  /admin/new-code      -> generate 1 access code
  GET  /admin/batch-codes   -> batch generate codes
  GET  /admin/codes         -> list active codes
  POST /auth/verify         -> get session token
  POST /auth/logout         -> release session lock

  WS   /ws         -> generic Claude Agent stream
  WS   /ws/chat    -> authenticated chat (requires token in first WS message)

Start:
  uv run uvicorn web.app:app --host 0.0.0.0 --port 8000
"""

import warnings

warnings.warn(
    "channels.web.app is deprecated. "
    "New frontend should connect to autoservice.web_gateway instead.",
    DeprecationWarning,
    stacklevel=2,
)

import asyncio
import json
import mimetypes
import os
import re
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# Fix SVG MIME type
mimetypes.add_type("image/svg+xml", ".svg")

# Load .env file if present
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path, encoding="utf-8") as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())


# ── Paths & config ────────────────────────────────────────────────────────
ROOT             = Path(__file__).parent.parent.parent
STATIC           = Path(__file__).parent / "static"
AUTOSERVICE_DIR  = ROOT / ".autoservice"
SESSIONS_DIR     = ROOT / ".autoservice" / "database" / "sessions"
LEADS_DIR    = ROOT / ".autoservice" / "database" / "knowledge_base" / "leads"

SERVER_PORT          = int(os.getenv("DEMO_PORT", "8000"))
IDLE_TIMEOUT_SECONDS = int(os.getenv("IDLE_TIMEOUT_MINUTES", "15")) * 60
ADMIN_KEY            = os.getenv("DEMO_ADMIN_KEY") or secrets.token_urlsafe(10)

# ── Configure submodules ──────────────────────────────────────────────────
from channels.web import auth
from channels.web import plugin_kb
from channels.web import session_persistence as sessions
from channels.web import websocket as ws_handlers

auth.configure(
    admin_key=ADMIN_KEY,
    idle_timeout_seconds=IDLE_TIMEOUT_SECONDS,
    auth_file=ROOT / ".autoservice" / "database" / "auth_store.json",
)
auth.load_auth()

plugin_kb.configure(root=ROOT)
sessions.configure(sessions_dir=SESSIONS_DIR)
ws_handlers.configure(
    channel_server_url=f"ws://localhost:{os.getenv('CHANNEL_SERVER_PORT', '9999')}"
)

_plugin_dir = ROOT / "plugins"


# ── Lifespan ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    asyncio.create_task(auth.idle_purge_loop())

    # Discover plugins and mount HTTP routes
    try:
        from socialware.plugin_loader import discover
        plugins = discover(ROOT / "plugins")
        for plugin in plugins:
            for route in plugin.routes:
                method = route.method.upper()
                if method == "GET":
                    app.get(route.path)(route.handler)
                elif method == "POST":
                    app.post(route.path)(route.handler)
                elif method == "PUT":
                    app.put(route.path)(route.handler)
                elif method == "DELETE":
                    app.delete(route.path)(route.handler)
            print(f"  Plugin '{plugin.name}': {len(plugin.tools)} tools, {len(plugin.routes)} routes", flush=True)
    except Exception as e:
        print(f"  [warn] Plugin discovery skipped: {e}", flush=True)

    sep = "=" * 60
    print(f"\n{sep}")
    print("  AutoService Web Server")
    cs_port = os.getenv("CHANNEL_SERVER_PORT", "9999")
    print(f"  Channel    : ws://localhost:{cs_port}")
    print(f"  Admin key  : {ADMIN_KEY}")
    print(f"  New code   : http://localhost:{SERVER_PORT}/admin/new-code?key={ADMIN_KEY}")
    print(f"  Demo login : http://localhost:{SERVER_PORT}/login")
    print(sep + "\n")

    yield
    # Shutdown (nothing to clean up)


# ── FastAPI app ───────────────────────────────────────────────────────────
app = FastAPI(title="AutoService Web", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


# ── Auth routes ───────────────────────────────────────────────────────────
app.get("/admin/new-code")(auth.admin_new_code)
app.get("/admin/batch-codes")(auth.admin_batch_codes)
app.get("/admin/codes")(auth.admin_list_codes)
app.post("/auth/verify")(auth.auth_verify)
app.post("/auth/logout")(auth.auth_logout)


# ── Page routes ───────────────────────────────────────────────────────────
@app.get("/")
async def page_index():
    return RedirectResponse(url="/login")


@app.get("/login")
async def page_login():
    return FileResponse(STATIC / "login.html")


@app.get("/chat")
async def page_chat():
    """Serve the chat page. Plugins can provide their own chat.html in static/."""
    # Check plugin static dirs first
    if _plugin_dir.exists():
        for _pd in sorted(_plugin_dir.iterdir()):
            if _pd.name.startswith("_"):
                continue
            candidate = _pd / "static" / "chat.html"
            if candidate.exists():
                return FileResponse(candidate)
    # Fallback to built-in static
    chat_html = STATIC / "chat.html"
    if chat_html.exists():
        return FileResponse(chat_html)
    raise HTTPException(404, "No chat page available. Install a plugin with static/chat.html.")


@app.get("/explain/{path:path}")
async def serve_explain(path: str):
    """Serve generated explain flow visualization pages."""
    file = AUTOSERVICE_DIR / "explain" / path
    if file.exists() and file.suffix == ".html":
        return FileResponse(file)
    raise HTTPException(404, "Explain page not found")


# ── WebSocket routes ──────────────────────────────────────────────────────
app.websocket("/ws")(ws_handlers.ws_generic)
app.websocket("/ws/chat")(ws_handlers.ws_chat)
app.websocket("/ws/cinnox")(ws_handlers.ws_chat)  # alias for plugin chat.html


# ── KB search HTTP endpoint ──────────────────────────────────────────────
@app.get("/api/kb_search")
async def api_kb_search(
    query: str = Query(""),
    top_k: int = Query(10),
    source_filter: str = Query(""),
    countries: str = Query(""),
):
    mod = plugin_kb.get_kb_search()
    if mod is None or not query.strip():
        return []
    sf = [s.strip() for s in source_filter.split(",") if s.strip()] or None
    cl = [c.strip() for c in countries.split(",") if c.strip()] or None
    results = mod.search(query.strip(), top_k=top_k, source_filter=sf, countries=cl)
    return [
        {
            "source_name": r["source_name"],
            "section":     r.get("section", ""),
            "content":     r["content"],
            "score":       r["score"],
        }
        for r in results
    ]


@app.get("/api/route_query")
async def api_route_query(query: str = Query("")):
    """Route a customer query -- returns domain/region/role JSON."""
    mod = plugin_kb.get_route_query()
    if mod is None or not query.strip():
        return {"error": "route_query module not available"}
    return mod.route(query.strip())


# ── Save lead HTTP endpoint ──────────────────────────────────────────────
@app.post("/api/save_lead")
async def api_save_lead(request: Request):
    """Save a collected lead (tolerant JSON parser)."""
    raw = await request.body()
    raw_str = raw.decode("utf-8", errors="replace").strip()
    body = None
    try:
        body = json.loads(raw_str)
    except json.JSONDecodeError:
        fixed = raw_str.replace('\\"', '"').replace("'", '"')
        try:
            body = json.loads(fixed)
        except json.JSONDecodeError:
            pass
    if not body or not isinstance(body, dict):
        raise HTTPException(400, "Invalid JSON body")
    customer_type = body.get("type", "").strip()
    if customer_type not in ("new_customer", "existing_customer", "partner"):
        raise HTTPException(400, f"Invalid type: {customer_type!r}")
    data = body.get("data")
    if not isinstance(data, dict):
        try:
            data = json.loads(data) if isinstance(data, str) else {}
        except Exception:
            data = {}
    LEADS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    record = {"type": customer_type, "data": data, "created_at": now.isoformat()}
    filename = f"{customer_type}_{now.strftime('%Y%m%d_%H%M%S')}.json"
    (LEADS_DIR / filename).write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[save_lead] {customer_type} -> {filename}", flush=True)
    return {"status": "ok", "file": filename}


# ── Sessions API ─────────────────────────────────────────────────────────
@app.get("/api/sessions")
async def api_list_sessions(token: str = Query("")):
    if not auth.valid_token(token):
        raise HTTPException(401, "Invalid or expired session")
    caller_code = auth.get_code_for_token(token)
    code_dir = sessions.session_dir_for_code(caller_code)
    files = sorted(code_dir.glob("session_*.json"), reverse=True)
    result = []
    for f in files[:50]:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("turn_count", 0) == 0:
                continue
            result.append({
                "id":            f.stem,
                "mode":          data.get("mode", "sales"),
                "customer_type": data.get("customer_type", "unknown"),
                "resolution":    data.get("resolution", "unknown"),
                "turn_count":    data.get("turn_count", 0),
                "created_at":    data.get("created_at", ""),
                "can_resume":    bool(data.get("conversation")),
            })
        except Exception:
            pass
    return result


@app.get("/api/sessions/{session_id}")
async def api_get_session(session_id: str, token: str = Query("")):
    if not auth.valid_token(token):
        raise HTTPException(401, "Invalid or expired session")
    if not re.match(r'^session_\d{8}_\d{6}$', session_id):
        raise HTTPException(400, "Invalid session id")
    caller_code = auth.get_code_for_token(token)
    code_dir = sessions.session_dir_for_code(caller_code)
    f = code_dir / f"{session_id}.json"
    if not f.exists():
        raise HTTPException(404, "Session not found")
    data = json.loads(f.read_text(encoding="utf-8"))
    data.pop("claude_session_id", None)
    data.pop("access_code", None)
    data["can_resume"] = bool(data.get("conversation"))
    return data


# ── Changelog endpoint ───────────────────────────────────────────────────
_CHANGELOG_FILE = ROOT / "web" / "CHANGELOG.md"

@app.get("/api/changelog")
async def api_changelog(lang: str = Query("en")):
    if not _CHANGELOG_FILE.exists():
        return {"version": "v0.0.0", "content": ""}
    text = _CHANGELOG_FILE.read_text(encoding="utf-8")
    m = re.search(r"<!--\s*VERSION:([\d.]+)\s*-->", text)
    ver = f"v{m.group(1)}" if m else "v0.0.0"
    tag = "ZH" if lang.startswith("zh") else "EN"
    sections = re.split(r"<!--\s*(EN|ZH)\s*-->", text)
    content = ""
    for i, sec in enumerate(sections):
        if sec.strip() == tag and i + 1 < len(sections):
            content = sections[i + 1]
            break
    if not content:
        content = re.sub(r"<!--.*?-->\n?", "", text)
    content = content.strip()
    return {"version": ver, "content": content}


# ── Standalone entry point ────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT)
