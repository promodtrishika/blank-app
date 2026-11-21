"""A small Microsoft Graph client: what the portal needs and nothing more.

App-only authentication (client credentials), retries on throttling and
transient failures with the server's Retry-After, @odata.nextLink paging, and
JSON batching of up to 20 requests per call.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Iterator
from urllib.parse import quote

import requests

from app.sharepoint.config import SharePointConfig

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 6
BATCH_SIZE = 20          # Graph's limit per $batch request
MAX_WAIT_SECONDS = 60


class GraphError(Exception):
    def __init__(self, status: int, code: str, message: str, response=None):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.response = response


def _error_from(resp: requests.Response) -> GraphError:
    try:
        err = resp.json().get("error", {})
        code, message = err.get("code", "unknown"), err.get("message", resp.text[:300])
    except ValueError:
        code, message = "unknown", resp.text[:300]
    return GraphError(resp.status_code, code, message, resp)


class GraphClient:
    # Tests point every client at a fake Graph by setting this to a
    # zero-argument factory returning a requests.Session.
    session_factory: Callable[[], requests.Session] | None = None
    sleep_override: Callable[[float], None] | None = None

    def __init__(self, config: SharePointConfig,
                 session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.config = config
        factory = GraphClient.session_factory
        self.session = session or (factory() if factory else requests.Session())
        sleep = GraphClient.sleep_override or sleep
        self.sleep = sleep
        self._token: str | None = None
        self._token_expires = 0.0
        self._lock = threading.Lock()
        self._site_id: str | None = None
        self._lists: dict[str, str] | None = None
        self._drives: dict[str, str] = {}

    # --- authentication -------------------------------------------------

    def token(self, force: bool = False) -> str:
        with self._lock:
            if not force and self._token and time.time() < self._token_expires - 60:
                return self._token
            url = f"{self.config.login_url}/{self.config.tenant_id}/oauth2/v2.0/token"
            scope = self.config.graph_url.split("/v1.0")[0].split("/beta")[0] + "/.default"
            resp = self.session.post(url, data={
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "scope": scope,
            }, timeout=30)
            if resp.status_code != 200:
                try:
                    body = resp.json()
                    raise GraphError(resp.status_code, body.get("error", "auth_failed"),
                                     body.get("error_description", resp.text[:300]), resp)
                except ValueError:
                    raise GraphError(resp.status_code, "auth_failed", resp.text[:300], resp)
            body = resp.json()
            self._token = body["access_token"]
            self._token_expires = time.time() + int(body.get("expires_in", 3600))
            return self._token

    # --- requests -------------------------------------------------------

    def url(self, path_or_url: str) -> str:
        if path_or_url.startswith("http"):
            return path_or_url
        return f"{self.config.graph_url}/{path_or_url.lstrip('/')}"

    def request(self, method: str, path_or_url: str, *, json: Any = None,
                data: bytes | None = None, params: dict | None = None,
                headers: dict | None = None, raw: bool = False,
                ok: tuple[int, ...] = ()) -> Any:
        """One call, retried on throttling and transient errors.

        Returns parsed JSON (or None for an empty body), or the Response when
        `raw` is set. Statuses in `ok` are returned instead of raised.
        """
        refreshed = False
        for attempt in range(1, MAX_ATTEMPTS + 1):
            hdrs = {"Authorization": f"Bearer {self.token()}"}
            if headers:
                hdrs.update(headers)
            try:
                resp = self.session.request(method, self.url(path_or_url), json=json,
                                            data=data, params=params, headers=hdrs,
                                            timeout=60)
            except requests.ConnectionError as exc:
                if attempt == MAX_ATTEMPTS:
                    raise GraphError(0, "connection_failed", str(exc)) from exc
                self.sleep(min(2 ** attempt, MAX_WAIT_SECONDS))
                continue
            if resp.status_code == 401 and not refreshed:
                self.token(force=True)
                refreshed = True
                continue
            if resp.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
                self.sleep(self._wait(resp.headers.get("Retry-After"), attempt))
                continue
            if resp.status_code >= 400 and resp.status_code not in ok:
                raise _error_from(resp)
            if raw or resp.status_code in ok:
                return resp
            if not resp.content:
                return None
            return resp.json()
        raise GraphError(0, "retries_exhausted", f"{method} {path_or_url}")

    @staticmethod
    def _wait(retry_after: str | None, attempt: int) -> float:
        try:
            return min(float(retry_after), MAX_WAIT_SECONDS)
        except (TypeError, ValueError):
            return min(2 ** attempt, MAX_WAIT_SECONDS)

    def get(self, path: str, **kw) -> Any:
        return self.request("GET", path, **kw)

    def pages(self, path: str, params: dict | None = None) -> Iterator[dict]:
        """Every page of a collection, following @odata.nextLink."""
        body = self.get(path, params=params)
        while True:
            yield body
            nxt = body.get("@odata.nextLink")
            if not nxt:
                return
            body = self.get(nxt)

    def all(self, path: str, params: dict | None = None) -> list[dict]:
        out: list[dict] = []
        for page in self.pages(path, params):
            out.extend(page.get("value", []))
        return out

    def batch(self, calls: list[dict]) -> list[dict]:
        """Run calls through $batch, 20 at a time, retrying throttled ones.

        Each call is {"method", "url" (relative to the Graph version root),
        optional "body"}. Returns one {"status", "body"} per call, in order.
        """
        results: list[dict | None] = [None] * len(calls)
        pending = list(range(len(calls)))
        attempt = 0
        while pending:
            attempt += 1
            retry: list[int] = []
            wait = 0.0
            for start in range(0, len(pending), BATCH_SIZE):
                chunk = pending[start:start + BATCH_SIZE]
                payload = {"requests": []}
                for idx in chunk:
                    call = calls[idx]
                    req = {"id": str(idx), "method": call["method"],
                           "url": "/" + call["url"].lstrip("/")}
                    if call.get("body") is not None:
                        req["body"] = call["body"]
                        req["headers"] = {"Content-Type": "application/json"}
                    payload["requests"].append(req)
                body = self.request("POST", "$batch", json=payload)
                for resp in body.get("responses", []):
                    idx = int(resp["id"])
                    status = int(resp.get("status", 500))
                    if status in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
                        retry.append(idx)
                        wait = max(wait, self._wait(
                            (resp.get("headers") or {}).get("Retry-After"), attempt))
                    else:
                        results[idx] = {"status": status, "body": resp.get("body")}
            pending = sorted(retry)
            if pending:
                self.sleep(wait)
        return [r if r is not None else {"status": 0, "body": None} for r in results]

    # --- sites, lists, drives -------------------------------------------

    def site_id(self) -> str:
        if self._site_id is None:
            site = self.get(f"sites/{self.config.site_hostname}:{self.config.site_path}")
            self._site_id = site["id"]
        return self._site_id

    def lists(self, refresh: bool = False) -> dict[str, str]:
        """displayName -> list id for every list and library on the site."""
        if self._lists is None or refresh:
            items = self.all(f"sites/{self.site_id()}/lists",
                             params={"$select": "id,displayName"})
            self._lists = {i["displayName"]: i["id"] for i in items}
        return self._lists

    def create_list(self, display_name: str, columns: list[dict],
                    template: str = "genericList") -> str:
        body = self.request("POST", f"sites/{self.site_id()}/lists", json={
            "displayName": display_name,
            "columns": columns,
            "list": {"template": template},
        })
        self.lists()[display_name] = body["id"]
        return body["id"]

    def drive_id(self, library: str) -> str:
        if library not in self._drives:
            drives = self.all(f"sites/{self.site_id()}/drives",
                              params={"$select": "id,name"})
            for d in drives:
                self._drives[d["name"]] = d["id"]
        if library not in self._drives:
            raise GraphError(404, "itemNotFound", f"No document library named {library!r}")
        return self._drives[library]

    @staticmethod
    def path_segment(text: str) -> str:
        return quote(text, safe="")
