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

import os
from time import time

import requests
from flask import session


class BackendError(Exception):
    """Raised for any failed call to a backend service. `str(exc)` is a
    message safe to show the user (flash it directly)."""

    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def _auth_headers():
    headers = {}
    username = session.get("username")
    role = session.get("role")
    token = session.get("access_token")
    if username:
        headers["X-User"] = username
    if role:
        headers["X-Role"] = role
    if token:
        headers["Authorization"] = f"Bearer {token}"
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


def _request(method, base_url, path, timeout=None, **kwargs):
    from flask import current_app
 
    url = f"{base_url}{path}"
    headers = kwargs.pop("headers", {}) or {}
    headers.update(_auth_headers())
 
    internal_token = current_app.config.get("INTERNAL_SERVICE_TOKEN") or os.environ.get(
        "INTERNAL_SERVICE_TOKEN", ""
    )
    if internal_token:
        headers["X-Internal-Token"] = internal_token
    try:
        resp = requests.request(method, url, headers=headers, timeout=timeout, **kwargs)
        print(f"[_request] <- response status: {resp.status_code} for {url}")
        return resp
    except requests.exceptions.RequestException as exc:
        raise BackendError(f"Could not reach {url} ({exc.__class__.__name__}).", 503)


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
