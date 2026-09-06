"""
Small wrapper around `requests` for calling the two FastAPI backends
(books service on :8001, users service on :8000).

Auth: backend/users/app/api/routers/users.py says CurrentUser is
"resolved via app.core.auth" using X-User / X-Role headers, so every
call sends those (populated from the Flask session after login). We
also send an Authorization: Bearer header in case auth.py turns out to
issue a JWT as well -- harmless if the backend ignores it. If your
auth.py works differently, this is the one place to change.
"""

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from flask import current_app, session

log = logging.getLogger(__name__)

# (connect timeout, read timeout) in seconds. Every call gets this unless
# a caller explicitly overrides it. Previously the default was `None`,
# i.e. no timeout at all -- a hung backend could hang a whole worker
# thread indefinitely.
DEFAULT_TIMEOUT = (3, 10)

_thread_local = threading.local()


class BackendError(Exception):
    """Raised for any failed call to a backend service. `str(exc)` is a
    message safe to show the user (flash it directly)."""

    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def _get_session():
    """One pooled, keep-alive requests.Session per worker thread.

    Reusing a Session avoids a fresh TCP (+TLS) handshake on every call --
    the previous code went through the bare `requests.request` module
    function, which internally opens and tears down a new Session (and
    connection) on every single call, even to a host it just talked to.
    """
    sess = getattr(_thread_local, "session", None)
    if sess is None:
        sess = requests.Session()
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
        sess.mount("http://", adapter)
        sess.mount("https://", adapter)
        _thread_local.session = sess
    return sess


def _build_headers(extra=None):
    """Reads Flask `session` / `current_app` -- only call this from a
    thread that has the active request/app context (i.e. never from
    inside a ThreadPoolExecutor worker)."""
    headers = dict(extra or {})

    username = session.get("username")
    role = session.get("role")
    token = session.get("access_token")
    if username:
        headers["X-User"] = username
    if role:
        headers["X-Role"] = role
    if token:
        headers["Authorization"] = f"Bearer {token}"

    internal_token = current_app.config.get("INTERNAL_SERVICE_TOKEN") or os.environ.get(
        "INTERNAL_SERVICE_TOKEN", ""
    )
    if internal_token:
        headers["X-Internal-Token"] = internal_token

    return headers


def _raise_for_error(resp):
    if resp.status_code >= 400:
        detail = None
        try:
            detail = resp.json().get("detail")
        except Exception:
            pass
        if isinstance(detail, list):
            # FastAPI validation errors come back as a list of dicts.
            detail = "; ".join(d.get("msg", str(d)) for d in detail)
        raise BackendError(detail or f"Request failed ({resp.status_code}).", resp.status_code)


def _do_request(method, url, headers, timeout, **kwargs):
    """Context-free -- safe to call from a worker thread. Headers must
    already be fully built (see _build_headers)."""
    try:
        resp = _get_session().request(method, url, headers=headers, timeout=timeout, **kwargs)
        log.debug("<- %s %s", resp.status_code, url)
        return resp
    except requests.exceptions.RequestException as exc:
        raise BackendError(f"Could not reach {url} ({exc.__class__.__name__}).", 503)


def _request(method, base_url, path, timeout=None, headers=None, **kwargs):
    url = f"{base_url}{path}"
    full_headers = _build_headers(headers)
    return _do_request(method, url, full_headers, timeout or DEFAULT_TIMEOUT, **kwargs)


def get_json(base_url, path, **kwargs):
    resp = _request("GET", base_url, path, **kwargs)
    _raise_for_error(resp)
    if not resp.content:
        return None
    return resp.json()


def post_json(base_url, path, json=None, **kwargs):
    resp = _request("POST", base_url, path, json=json, **kwargs)
    _raise_for_error(resp)
    if not resp.content:
        return {}
    return resp.json()


def post_form(base_url, path, data=None, files=None, **kwargs):
    resp = _request("POST", base_url, path, data=data, files=files, **kwargs)
    _raise_for_error(resp)
    if not resp.content:
        return {}
    return resp.json()


def get_file(base_url, path, **kwargs):
    """For .xlsx export/download endpoints -- returns the raw response so
    the Flask route can stream bytes + content-type straight through."""
    resp = _request("GET", base_url, path, **kwargs)
    _raise_for_error(resp)
    return resp


def parallel_get_json(calls):
    """
    Run several independent GET calls concurrently (they must not depend
    on each other's results) and return their parsed JSON in the same
    order the calls were given.

    calls: list of (base_url, path, kwargs) tuples. kwargs may include
    e.g. {"params": {...}, "timeout": (3, 10)}.

    Headers are built once per call HERE, in the calling (request)
    thread, before handing off to the pool -- worker threads never touch
    Flask's `session`/`current_app`.

    Per-call failures are returned as a BackendError in that slot instead
    of raising immediately, so one unhealthy service doesn't discard a
    result you already got from a healthy one. Check each slot with
    `isinstance(result, BackendError)`.
    """
    if not calls:
        return []

    prepared = []
    for base_url, path, kwargs in calls:
        kwargs = dict(kwargs or {})
        headers = _build_headers(kwargs.pop("headers", None))
        timeout = kwargs.pop("timeout", None) or DEFAULT_TIMEOUT
        prepared.append((f"{base_url}{path}", headers, timeout, kwargs))

    results = [None] * len(prepared)

    def _run(i, url, headers, timeout, kwargs):
        try:
            resp = _do_request("GET", url, headers, timeout, **kwargs)
            _raise_for_error(resp)
            return i, (resp.json() if resp.content else None)
        except BackendError as exc:
            return i, exc

    with ThreadPoolExecutor(max_workers=max(len(prepared), 1)) as pool:
        futures = [pool.submit(_run, i, *args) for i, args in enumerate(prepared)]
        for fut in as_completed(futures):
            i, value = fut.result()
            results[i] = value

    return results