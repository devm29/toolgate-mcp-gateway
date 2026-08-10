from __future__ import annotations

from html import escape
from string import Template

from toolgate.auth.scopes import DESCRIPTIONS

_PAGE = Template("""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>$title · Toolgate</title>
<style>
  :root { color-scheme: light dark; --bg:#f5f5f7; --card:#fff; --fg:#1d1d1f; --muted:#6e6e73; --border:#e5e5ea;
          --accent:#0071e3; --danger:#d70015; }
  @media (prefers-color-scheme: dark) { :root { --bg:#000; --card:#1c1c1e; --fg:#f5f5f7; --muted:#98989d;
          --border:rgba(255,255,255,.1); --accent:#0a84ff; --danger:#ff453a; } }
  * { box-sizing: border-box; }
  body { margin:0; min-height:100dvh; display:grid; place-items:center; background:var(--bg); color:var(--fg);
         font:15px/22px -apple-system, BlinkMacSystemFont, "SF Pro Text", Inter, "Helvetica Neue", sans-serif;
         letter-spacing:-0.01em; -webkit-font-smoothing:antialiased; padding:24px; }
  main { width:100%; max-width:380px; background:var(--card); border:1px solid var(--border); border-radius:18px;
         padding:32px 28px; box-shadow:0 12px 40px rgb(0 0 0 / .08); }
  .mark { width:44px; height:44px; border-radius:12px; background:var(--accent); display:grid; place-items:center;
          color:#fff; font-weight:600; margin-bottom:20px; }
  h1 { font-size:22px; line-height:28px; font-weight:600; margin:0 0 6px; }
  p { margin:0 0 20px; color:var(--muted); font-size:14px; }
  label { display:block; font-size:13px; font-weight:500; margin:0 0 6px; }
  input[type=text], input[type=password] { width:100%; height:40px; border-radius:10px; border:1px solid var(--border);
         background:transparent; color:var(--fg); padding:0 12px; font:inherit; margin-bottom:14px; }
  input:focus-visible, button:focus-visible { outline:none; box-shadow:0 0 0 4px rgb(0 113 227 / .35);
         border-color:var(--accent); }
  ul { list-style:none; margin:0 0 24px; padding:0; border:1px solid var(--border); border-radius:12px; }
  li { padding:10px 14px; font-size:14px; } li + li { border-top:1px solid var(--border); }
  li small { display:block; color:var(--muted); font-size:12px; }
  .row { display:flex; gap:10px; }
  button { flex:1; height:40px; border-radius:10px; border:0; font:500 14px/1 inherit; cursor:pointer;
           transition:transform .12s, opacity .12s; }
  button:active { transform:scale(.98); }
  .primary { background:var(--accent); color:#fff; }
  .secondary { background:var(--bg); color:var(--fg); }
  .error { color:var(--danger); font-size:13px; margin:-4px 0 14px; }
  .meta { font-size:12px; color:var(--muted); margin-top:18px; word-break:break-all; }
</style>
</head>
<body><main><div class="mark" aria-hidden="true">T</div>$body</main></body>
</html>""")


def _page(title: str, body: str) -> str:
    return _PAGE.substitute(title=escape(title), body=body)


def login_page(*, return_to: str, csrf: str, error: str | None = None, username: str = "") -> str:
    error_html = f'<p class="error" role="alert">{escape(error)}</p>' if error else ""
    body = f"""
<h1>Sign in to Toolgate</h1>
<p>An application wants to connect to your Toolgate account.</p>
<form method="post" action="/oauth/login">
  <input type="hidden" name="return_to" value="{escape(return_to)}">
  <input type="hidden" name="csrf" value="{escape(csrf)}">
  <label for="username">Username</label>
  <input id="username" name="username" type="text" autocomplete="username"
         required value="{escape(username)}" autofocus>
  <label for="password">Password</label>
  <input id="password" name="password" type="password" autocomplete="current-password" required>
  {error_html}
  <div class="row"><button class="primary" type="submit">Continue</button></div>
</form>"""
    return _page("Sign in", body)


def consent_page(
    *,
    client_name: str,
    redirect_uri: str,
    scopes: list[str],
    username: str,
    hidden: dict[str, str],
) -> str:
    items = "".join(f"<li>{escape(DESCRIPTIONS.get(s, s))}<small>{escape(s)}</small></li>" for s in scopes)
    fields = "".join(f'<input type="hidden" name="{escape(k)}" value="{escape(v)}">' for k, v in hidden.items())
    body = f"""
<h1>Allow {escape(client_name)}?</h1>
<p>Signed in as {escape(username)}. This application will be able to:</p>
<ul>{items}</ul>
<form method="post" action="/oauth/authorize">
  {fields}
  <div class="row">
    <button class="secondary" type="submit" name="decision" value="deny">Don't allow</button>
    <button class="primary" type="submit" name="decision" value="allow">Allow</button>
  </div>
</form>
<div class="meta">You will return to {escape(redirect_uri)}</div>"""
    return _page("Authorize", body)


def error_page(message: str) -> str:
    body = f"<h1>Can't continue</h1><p>{escape(message)}</p>"
    return _page("Authorization error", body)


def signed_out_page() -> str:
    return _page("Signed out", "<h1>Signed out</h1><p>You are signed out of Toolgate.</p>")
