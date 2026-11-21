"""An in-memory Microsoft Graph for tests: SharePoint sites, lists, list
items, delta, document libraries with versions, $batch, and the token
endpoint — the endpoints the portal uses, with the rules SharePoint enforces
(unknown fields rejected, number and dateTime types, the 255-character
single-line limit, Title required).

Use it in-process (`session()` mounts it as a requests adapter) or as an HTTP
server (`python tests/fake_graph.py --port 8765`) for a browser check.
"""

from __future__ import annotations

import itertools
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import requests
from requests.adapters import BaseAdapter

SECRET = "fake-secret"
BUILTIN_COLUMNS = ["Title", "ID", "Created", "Modified", "Author", "Editor",
                   "ContentType", "Attachments"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeGraph:
    def __init__(self, hostname="contoso.sharepoint.com", site_path="/sites/RTPS-QAP"):
        self.lock = threading.RLock()
        self.site_id = f"{hostname},{uuid.uuid4()},{uuid.uuid4()}"
        self.hostname, self.site_path = hostname, site_path
        self.lists: dict[str, dict] = {}
        self.drives: dict[str, dict] = {}
        self.seq = itertools.count(1)
        self.log: list[tuple[str, str]] = []
        self.throttle_next = 0          # whole requests answered with 429
        self.throttle_batch_items = 0   # sub-requests in a $batch answered with 429
        self.fail_status: int | None = None   # every request answered with this
        self.expired_tokens: set[str] = set()
        self.base = "https://graph.fake/v1.0"

    # --- public helpers for tests -------------------------------------

    def list_by_name(self, name: str) -> dict:
        return next(l for l in self.lists.values() if l["displayName"] == name)

    def items(self, name: str) -> list[dict]:
        return [i["fields"] for i in self.list_by_name(name)["items"].values()]

    def add_item_directly(self, name: str, fields: dict) -> str:
        """What a person editing the list in SharePoint does."""
        with self.lock:
            lst = self.list_by_name(name)
            return self._create_item(lst, fields)["id"]

    def edit_item_directly(self, name: str, item_id: str, fields: dict) -> None:
        with self.lock:
            lst = self.list_by_name(name)
            lst["items"][item_id]["fields"].update(fields)
            self._touch(lst, item_id)

    def delete_item_directly(self, name: str, item_id: str) -> None:
        with self.lock:
            lst = self.list_by_name(name)
            del lst["items"][item_id]
            lst["changes"].append((next(self.seq), item_id, True))

    def expire_delta_tokens(self) -> None:
        for lst in self.lists.values():
            for seq, *_ in lst["changes"]:
                self.expired_tokens.add(str(seq))
            self.expired_tokens.add("0")

    # --- transport ------------------------------------------------------

    def session(self) -> requests.Session:
        s = requests.Session()
        adapter = _Adapter(self)
        s.mount("https://graph.fake", adapter)
        s.mount("https://login.fake", adapter)
        return s

    def handle(self, method: str, url: str, body: bytes | None) -> tuple[int, dict, bytes]:
        with self.lock:
            parts = urlsplit(url)
            path = unquote(parts.path)
            query = {k: v[0] for k, v in parse_qs(parts.query).items()}
            self.log.append((method, path))
            if path.endswith("/oauth2/v2.0/token"):
                form = {k: v[0] for k, v in parse_qs((body or b"").decode()).items()}
                if form.get("client_secret") != SECRET:
                    return _json(401, {"error": "invalid_client",
                                       "error_description": "AADSTS7000215: Invalid client secret."})
                return _json(200, {"access_token": "fake-token", "expires_in": 3600})
            if self.fail_status:
                return _json(self.fail_status, _err("serviceNotAvailable", "down"))
            if self.throttle_next:
                self.throttle_next -= 1
                return _json(429, _err("TooManyRequests", "slow down"), {"Retry-After": "0"})
            rel = path.split("/v1.0/", 1)[1] if "/v1.0/" in path else path.lstrip("/")
            self.base = url.split("/v1.0/")[0] + "/v1.0"
            try:
                return self._route(method, rel, query, body)
            except _Http as e:
                return _json(e.status, _err(e.code, e.message))

    # --- routing --------------------------------------------------------

    def _route(self, method, rel, q, body):
        data = json.loads(body) if body and method in ("POST", "PATCH") and rel != "$batch_raw" else None
        if rel == "$batch" and method == "POST":
            return self._batch(data)
        m = re.fullmatch(r"sites/([^/:]+):(/.+)", rel)
        if m and method == "GET":
            if m.group(1) != self.hostname or m.group(2) != self.site_path:
                raise _Http(404, "itemNotFound", "Requested site could not be found")
            return _json(200, {"id": self.site_id, "webUrl": f"https://{self.hostname}{self.site_path}"})
        m = re.fullmatch(r"sites/([^/]+)/(.*)", rel)
        if m:
            if m.group(1) != self.site_id:
                raise _Http(404, "itemNotFound", "site")
            return self._site(method, m.group(2), q, data)
        m = re.fullmatch(r"drives/([^/]+)/(.*)", rel)
        if m:
            return self._drive(method, m.group(1), m.group(2), q, body)
        raise _Http(400, "BadRequest", f"Unsupported {method} {rel}")

    def _site(self, method, rest, q, data):
        if rest == "lists" and method == "GET":
            return _json(200, {"value": [{"id": i, "displayName": l["displayName"]}
                                         for i, l in self.lists.items()]})
        if rest == "lists" and method == "POST":
            name = data["displayName"]
            if any(l["displayName"] == name for l in self.lists.values()):
                raise _Http(409, "nameAlreadyExists", "A list with that name exists")
            lid = str(uuid.uuid4())
            template = (data.get("list") or {}).get("template", "genericList")
            cols = {c["name"]: c for c in data.get("columns", [])}
            self.lists[lid] = {"displayName": name, "template": template, "columns": cols,
                               "items": {}, "next_id": 1, "changes": []}
            if template == "documentLibrary":
                self.drives[str(uuid.uuid4())] = {"name": name, "files": {}, "paths": {}}
            return _json(201, {"id": lid, "displayName": name})
        if rest == "drives" and method == "GET":
            return _json(200, {"value": [{"id": i, "name": d["name"]}
                                         for i, d in self.drives.items()]})
        m = re.fullmatch(r"lists/([^/]+)/(.*)", rest)
        if not m or m.group(1) not in self.lists:
            raise _Http(404, "itemNotFound", "list")
        lst = self.lists[m.group(1)]
        sub = m.group(2)
        lid = m.group(1)
        if sub == "columns":
            if method == "GET":
                return _json(200, {"value": [{"name": n} for n in [*BUILTIN_COLUMNS, *lst["columns"]]]})
            if method == "POST":
                lst["columns"][data["name"]] = data
                return _json(201, data)
        if sub == "items" and method == "GET":
            return self._page(lid, list(lst["items"].values()), q, "items")
        if sub == "items" and method == "POST":
            return _json(201, self._create_item(lst, data.get("fields", {})))
        if sub == "items/delta" and method == "GET":
            return self._delta(lid, lst, q)
        m = re.fullmatch(r"items/([^/]+)(/fields)?", sub)
        if m:
            iid = m.group(1)
            if iid not in lst["items"]:
                raise _Http(404, "itemNotFound", "The specified list item was not found")
            if method == "PATCH" and m.group(2):
                self._validate(lst, data, partial=True)
                lst["items"][iid]["fields"].update(data)
                self._touch(lst, iid)
                return _json(200, lst["items"][iid]["fields"])
            if method == "DELETE" and not m.group(2):
                del lst["items"][iid]
                lst["changes"].append((next(self.seq), iid, True))
                return 204, {}, b""
            if method == "GET":
                return _json(200, self._item(lst["items"][iid]))
        raise _Http(400, "BadRequest", f"Unsupported {method} lists/.../{sub}")

    # --- list items -----------------------------------------------------

    def _validate(self, lst, fields, partial=False):
        for name, value in fields.items():
            if name in ("Title",):
                if value is not None and len(str(value)) > 255:
                    raise _Http(400, "invalidRequest", "Title is longer than 255")
                continue
            col = lst["columns"].get(name)
            if col is None:
                raise _Http(400, "invalidRequest", f"Field '{name}' is not recognized")
            if value is None:
                continue
            if "number" in col and not isinstance(value, (int, float)):
                raise _Http(400, "invalidRequest", f"Field '{name}' expects a number")
            if "dateTime" in col and not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", str(value)):
                raise _Http(400, "invalidRequest", f"Field '{name}' expects an ISO date")
            if "text" in col and not col["text"].get("allowMultipleLines") and len(str(value)) > 255:
                raise _Http(400, "invalidRequest", f"Field '{name}' is longer than 255")
        if not partial and not fields.get("Title"):
            raise _Http(400, "invalidRequest", "Title is required")

    def _create_item(self, lst, fields):
        self._validate(lst, fields)
        iid = str(lst["next_id"])
        lst["next_id"] += 1
        now = _now()
        lst["items"][iid] = {"id": iid, "created": now,
                             "fields": {**fields, "id": iid, "ContentType": "Item",
                                        "Created": now, "Modified": now}}
        lst["changes"].append((next(self.seq), iid, False))
        return self._item(lst["items"][iid])

    def _touch(self, lst, iid):
        lst["items"][iid]["fields"]["Modified"] = _now()
        lst["changes"].append((next(self.seq), iid, False))

    def _item(self, item):
        return {"id": item["id"], "createdDateTime": item["created"],
                "fields": dict(item["fields"])}

    def _page(self, lid, records, q, kind, extra_link=None):
        top = int(q.get("$top", 200))
        skip = int(q.get("skip", 0))
        chunk = records[skip:skip + top]
        body = {"value": [self._item(r) if "fields" in r and "deleted" not in r else r
                          for r in chunk]}
        if skip + top < len(records):
            nq = {**q, "skip": skip + top}
            body["@odata.nextLink"] = f"{self.base}/sites/{self.site_id}/lists/{lid}/{kind}?{urlencode(nq)}"
        elif extra_link:
            body.update(extra_link)
        return _json(200, body)

    def _delta(self, lid, lst, q):
        token = q.get("token")
        head = max([s for s, *_ in lst["changes"]], default=0)
        link = {"@odata.deltaLink": f"{self.base}/sites/{self.site_id}/lists/{lid}/items/delta?"
                                    + urlencode({"token": head, "$expand": "fields"})}
        if token == "latest":
            return _json(200, {"value": [], **link})
        if token is None:
            records = list(lst["items"].values())
        else:
            if token in self.expired_tokens:
                return _json(410, _err("resyncRequired", "Resync required"),
                             {"Location": f"{self.base}/sites/{self.site_id}/lists/{lid}/items/delta"})
            since = int(token)
            latest = {}
            for s, iid, deleted in lst["changes"]:
                if s > since:
                    latest[iid] = deleted
            records = []
            for iid, deleted in latest.items():
                if deleted or iid not in lst["items"]:
                    records.append({"id": iid, "deleted": {"state": "deleted"}})
                else:
                    records.append(lst["items"][iid])
        q = {k: v for k, v in q.items()}
        return self._page(lid, records, q, "items/delta", extra_link=link)

    # --- drives ---------------------------------------------------------

    def _drive(self, method, did, rest, q, body):
        drive = self.drives.get(did)
        if drive is None:
            raise _Http(404, "itemNotFound", "drive")
        m = re.fullmatch(r"root:/(.+):/content", rest)
        if m and method == "PUT":
            path = m.group(1)
            iid = drive["paths"].get(path)
            if iid is None:
                iid = str(uuid.uuid4())
                drive["paths"][path] = iid
                drive["files"][iid] = {"path": path, "versions": []}
            f = drive["files"][iid]
            f["versions"].append({"id": f"{len(f['versions']) + 1}.0",
                                  "lastModifiedDateTime": f"{_now()}#{len(f['versions']):04d}",
                                  "content": body or b""})
            return _json(201, {"id": iid, "name": path.rsplit("/", 1)[-1],
                               "webUrl": f"https://{self.hostname}{self.site_path}/"
                                         f"{drive['name'].replace(' ', '%20')}/{path}"})
        m = re.fullmatch(r"items/([^/]+)/content", rest)
        if m and method == "GET":
            f = drive["files"].get(m.group(1)) or _raise(404)
            return 200, {"Content-Type": "application/octet-stream"}, f["versions"][-1]["content"]
        m = re.fullmatch(r"items/([^/]+)/versions", rest)
        if m and method == "GET":
            f = drive["files"].get(m.group(1)) or _raise(404)
            return _json(200, {"value": [{"id": v["id"], "lastModifiedDateTime": v["lastModifiedDateTime"]}
                                         for v in reversed(f["versions"])]})
        m = re.fullmatch(r"items/([^/]+)/versions/([^/]+)/content", rest)
        if m and method == "GET":
            f = drive["files"].get(m.group(1)) or _raise(404)
            v = next((v for v in f["versions"] if v["id"] == m.group(2)), None) or _raise(404)
            return 200, {"Content-Type": "application/octet-stream"}, v["content"]
        raise _Http(400, "BadRequest", f"Unsupported drive call {method} {rest}")

    # --- $batch ---------------------------------------------------------

    def _batch(self, data):
        reqs = data.get("requests", [])
        if len(reqs) > 20:
            raise _Http(400, "BadRequest", "A $batch holds at most 20 requests")
        out = []
        for r in reqs:
            if self.throttle_batch_items:
                self.throttle_batch_items -= 1
                out.append({"id": r["id"], "status": 429, "headers": {"Retry-After": "0"},
                            "body": _err("TooManyRequests", "slow down")})
                continue
            payload = json.dumps(r["body"]).encode() if r.get("body") is not None else None
            parts = urlsplit(r["url"])
            q = {k: v[0] for k, v in parse_qs(parts.query).items()}
            try:
                status, headers, body = self._route(r["method"], unquote(parts.path).lstrip("/"), q, payload)
            except _Http as e:
                status, headers, body = _json(e.status, _err(e.code, e.message))
            out.append({"id": r["id"], "status": status, "headers": headers,
                        "body": json.loads(body) if body else None})
        return _json(200, {"responses": out})


class _Http(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message


def _raise(status):
    raise _Http(status, "itemNotFound", "not found")


def _err(code, message):
    return {"error": {"code": code, "message": message}}


def _json(status, obj, headers=None):
    return status, {"Content-Type": "application/json", **(headers or {})}, json.dumps(obj).encode()


class _Adapter(BaseAdapter):
    def __init__(self, fake: FakeGraph):
        super().__init__()
        self.fake = fake

    def send(self, request, **kwargs):
        body = request.body
        if isinstance(body, str):
            body = body.encode()
        status, headers, content = self.fake.handle(request.method, request.url, body)
        resp = requests.Response()
        resp.status_code = status
        resp.headers.update(headers)
        resp._content = content
        resp.url = request.url
        resp.request = request
        return resp

    def close(self):
        pass


class FakeOIDC:
    """A minimal OpenID Connect provider standing in for Entra ID sign-in:
    discovery, an account picker, the code-for-token exchange, RS256 ID tokens."""

    def __init__(self, base: str, client_id: str = "client"):
        from authlib.jose import JsonWebKey

        self.base, self.client_id = base, client_id
        self.key = JsonWebKey.generate_key("RSA", 2048, is_private=True)
        self.codes: dict[str, dict] = {}

    def handle(self, method, path, query, body):
        from authlib.jose import jwt
        import time

        if path == "/oidc/.well-known/openid-configuration":
            return _json(200, {
                "issuer": f"{self.base}/oidc",
                "authorization_endpoint": f"{self.base}/oidc/authorize",
                "token_endpoint": f"{self.base}/oidc/token",
                "jwks_uri": f"{self.base}/oidc/jwks",
                "response_types_supported": ["code"],
                "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
                "scopes_supported": ["openid", "profile", "email"],
                "token_endpoint_auth_methods_supported": ["client_secret_post",
                                                          "client_secret_basic"],
            })
        if path == "/oidc/jwks":
            return _json(200, {"keys": [{**self.key.as_dict(is_private=False),
                                         "use": "sig", "alg": "RS256"}]})
        if path == "/oidc/authorize" and method == "GET":
            fields = "".join(f'<input type="hidden" name="{k}" value="{v}">'
                             for k, v in query.items())
            page = ("<!doctype html><title>Pick an account</title><h1>Sign in</h1>"
                    f'<form method="post" action="{self.base}/oidc/authorize">{fields}'
                    '<label>Email <input name="email" id="email"></label>'
                    '<label>Name <input name="name" id="name"></label>'
                    '<button id="go">Sign in</button></form>')
            return 200, {"Content-Type": "text/html"}, page.encode()
        if path == "/oidc/authorize" and method == "POST":
            form = {k: v[0] for k, v in parse_qs((body or b"").decode()).items()}
            code = uuid.uuid4().hex
            self.codes[code] = form
            target = (f"{form['redirect_uri']}?"
                      + urlencode({"code": code, "state": form.get("state", "")}))
            return 302, {"Location": target}, b""
        if path == "/oidc/token" and method == "POST":
            form = {k: v[0] for k, v in parse_qs((body or b"").decode()).items()}
            who = self.codes.pop(form.get("code", ""), None)
            if who is None:
                return _json(400, {"error": "invalid_grant"})
            now = int(time.time())
            claims = {"iss": f"{self.base}/oidc", "aud": self.client_id,
                      "sub": who["email"], "email": who["email"],
                      "preferred_username": who["email"], "name": who.get("name") or who["email"],
                      "iat": now, "exp": now + 3600}
            if who.get("nonce"):
                claims["nonce"] = who["nonce"]
            kid = self.key.as_dict().get("kid")
            token = jwt.encode({"alg": "RS256", **({"kid": kid} if kid else {})},
                               claims, self.key)
            return _json(200, {"access_token": "fake-access", "token_type": "Bearer",
                               "expires_in": 3600, "id_token": token.decode()})
        return _json(404, {"error": "not_found"})


def serve(port: int) -> None:
    """Run the fake as an HTTP server (for a browser check of the portal)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    fake = FakeGraph()
    oidc = FakeOIDC(f"http://127.0.0.1:{port}")

    class Handler(BaseHTTPRequestHandler):
        def _go(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            if self.path.startswith("/oidc"):
                parts = urlsplit(self.path)
                query = {k: v[0] for k, v in parse_qs(parts.query).items()}
                status, headers, content = oidc.handle(self.command, parts.path, query, body)
            else:
                status, headers, content = fake.handle(
                    self.command, f"http://127.0.0.1:{port}{self.path}", body)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _go

        def log_message(self, *a):
            pass

    print(f"fake Graph on http://127.0.0.1:{port} (site id {fake.site_id})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    serve(ap.parse_args().port)
