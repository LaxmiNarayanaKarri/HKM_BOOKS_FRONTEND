# services/auth.py
from functools import wraps
from flask import flash, jsonify, redirect, request, session, url_for
from services.permissions import roles_for


def _wants_json():
    return request.args.get("ajax") == "1" or request.is_json


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            if _wants_json():
                return jsonify(ok=False, message="Please log in."), 401
            return redirect(url_for("users.login"))
        return view(*args, **kwargs)
    return wrapped


def permission_required(action):
    """
    @permission_required("user_management")

    Roles are resolved from ROUTE_PERMISSIONS[action], not hardcoded
    here -- so updating permissions.py is enough, no route changes.
    """
    allowed_roles = roles_for(action)  # resolved at import time -- a typo'd action name fails fast on app startup, not on first request

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "username" not in session:
                if _wants_json():
                    return jsonify(ok=False, message="Please log in."), 401
                return redirect(url_for("users.login"))
            if session.get("role") not in allowed_roles:
                if _wants_json():
                    return jsonify(ok=False, message="You don't have permission to do that."), 403
                flash("You don't have permission to access that page.", "danger")
                return redirect(url_for("books.dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator