"""
'users' blueprint -> Users service (http://localhost:8000).

Everything under /api/users/* below is wired EXACTLY to the router you
sent me (app/api/routers/users.py):

    GET  /api/users                          -> user_management() [GET]
    POST /api/users                          -> user_management() [POST, add user]
    GET  /api/users/export                   -> export_users()
    POST /api/users/{username}/toggle        -> toggle_user()
    POST /api/users/{username}/delete        -> delete_user()
    POST /api/users/{username}/password      -> change_password()
    POST /api/users/{username}/role          -> change_role()

Two routes are NOT covered by anything you've sent me yet, so they're
best-effort placeholders -- clearly marked below:

    POST /login  -> guessed POST /api/auth/login   (needs app/api/routers/auth.py)
    GET  /volunteer-assignment -> guessed GET /api/volunteers (needs volunteers.py)

Send me those two router files and I'll lock these in the same way.
"""

from datetime import date

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for, Response

from services.api_client import BackendError, get_file, get_json, parallel_get_json, post_json

from services.auth import permission_required


bp = Blueprint("users", __name__)


def _base_url():
    return current_app.config["USER_SERVICE_URL"]

def _base_url_books():
    return current_app.config["BOOK_SERVICE_URL"]


def _logged_in():
    return "username" in session


def _require_login():
    if not _logged_in():
        return redirect(url_for("users.login"))
    return None


# ---------------------------------------------------------------- auth ---

@bp.route("/", methods=["GET", "POST"])
def login():
    if _logged_in():
        return redirect(url_for("books.sell_entry"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        try:
            # ASSUMPTION (send me auth.py to confirm/fix): POST
            # /api/auth/login with {"username", "password"} JSON,
            # returning at least the user's role. We accept either
            # {"user": {...}, "access_token": "..."} or a flat
            # {"username", "role", "access_token", ...} shape.
            data = post_json(_base_url(), "/api/auth/login",
                              json={"username": username, "password": password}) or {}
            user_info = data.get("user", data)
            session["username"] = user_info.get("username", username)
            session["role"] = user_info.get("role")
            session["name"] = user_info.get("name", username)
            session["access_token"] = data.get("access_token")
            return redirect(url_for("books.sell_entry"))
        except BackendError as exc:
            if exc.status_code == 503:
                flash("User Authentication service is offline (port 8000).", "danger")
            elif exc.status_code in (401, 403):
                flash("Invalid username or password.", "danger")
            else:
                flash(str(exc), "danger")

    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("users.login"))


# ------------------------------------------------------- user management ---

@bp.route("/users", methods=["GET", "POST"])
@permission_required("user_management")
def user_management():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp

    if request.method == "POST":
        payload = {
            "name": request.form.get("name", "").strip(),
            "mobile": request.form.get("mobile", "").strip(),
            "username": request.form.get("username", "").strip(),
            "password": request.form.get("password", ""),
            "role": request.form.get("role"),
        }
        try:
            result = post_json(_base_url(), "/api/users", json=payload)
            flash(result.get("message", "User added."), "success")
        except BackendError as exc:
            flash(str(exc), "danger")
        return redirect(url_for("users.user_management"))

    users_list, roles = [], []
    try:
        data = get_json(_base_url(), "/api/users") or {}
        users_list = data.get("users", [])
        roles = data.get("roles", [])
    except BackendError as exc:
        flash(str(exc), "danger")

    return render_template("user_management.html", users=users_list, roles=roles)


@bp.route("/users/export")
@permission_required("user_management")
def export_users():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    try:
        resp = get_file(_base_url(), "/api/users/export")
    except BackendError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("users.user_management"))
    return Response(
        resp.content,
        mimetype=resp.headers.get(
            "Content-Type",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        headers={
            "Content-Disposition": resp.headers.get(
                "Content-Disposition", 'attachment; filename="users.xlsx"'
            )
        },
    )


@bp.route("/users/<username>/toggle", methods=["POST"])
@permission_required("user_management")
def toggle_user(username):
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    try:
        result = post_json(_base_url(), f"/api/users/{username}/toggle")
        flash(result.get("message", "Updated."), "success")
    except BackendError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("users.user_management"))


@bp.route("/users/<username>/delete", methods=["POST"])
@permission_required("user_management")
def delete_user(username):
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    try:
        result = post_json(_base_url(), f"/api/users/{username}/delete")
        flash(result.get("message", "Deleted."), "success")
    except BackendError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("users.user_management"))


@bp.route("/users/<username>/password", methods=["POST"])
@permission_required("user_management")
def change_password(username):
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    try:
        result = post_json(
            _base_url(),
            f"/api/users/{username}/password",
            json={"password": request.form.get("password", "")},
        )
        flash(result.get("message", "Password updated."), "success")
    except BackendError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("users.user_management"))


@bp.route("/users/<username>/role", methods=["POST"])
@permission_required("user_management")
def change_role(username):
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    try:
        result = post_json(
            _base_url(),
            f"/api/users/{username}/role",
            json={"role": request.form.get("role")},
        )
        flash(result.get("message", "Role updated."), "success")
    except BackendError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("users.user_management"))


# --------------------------------------------------- volunteer assignment ---
# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

def _overview_filters(today_iso=None):
    """Pull the four overview filter params from query string or form body."""
    today_iso = today_iso or date.today().isoformat()
    return {
        "ov_date_from": (request.values.get("ov_date_from") or "").strip() or today_iso,
        "ov_date": (request.values.get("ov_date") or "").strip() or today_iso,
        "ov_location": (request.values.get("ov_location") or "all").strip() or "all",
        "ov_event": (request.values.get("ov_event") or "all").strip() or "all",
    }


def _build_filter_label(filters):
    bits = [
        filters["ov_location"] if filters["ov_location"] != "all" else "All Locations",
        filters["ov_event"] if filters["ov_event"] != "all" else "All Events",
    ]
    if filters["ov_date"]:
        bits.append(filters["ov_date"])
    elif filters["ov_date_from"]:
        bits.append(f"from {filters['ov_date_from']}")
    return " · ".join(bits)


def _fetch_overview_payload(filters):
    """
    Single source of truth for both the SSR page and the JSON overview API.

    The two backend calls below (users service + books service) are
    independent of each other -- neither needs the other's result -- so
    they're fired concurrently via parallel_get_json() instead of one
    after another. Each slot comes back either as the parsed JSON or, if
    that particular call failed, a BackendError -- so one unhealthy
    service doesn't wipe out data you already got from the other.
    """
    users_data, sales_data = parallel_get_json([
        (_base_url(), "/api/users/volunteers/data", {"params": filters}),
        (_base_url_books(), "/internal/location-overview", {"params": filters}),
    ])

    if isinstance(users_data, BackendError):
        flash(f"Could not load volunteer assignment data: {users_data}", "danger")
        users_data = {
            "volunteers": [],
            "locations": [],
            "assignments": [],
            "location_counts": {},
            "events": [],
        }

    if isinstance(sales_data, BackendError):
        flash(f"Could not load sales data: {sales_data}", "danger")
        sales_data = {"sales_by_location": {}, "sales_by_location_volunteer": {}, "total_sales": 0}

    return {
        "volunteers": users_data.get("volunteers", []),
        "locations": users_data.get("locations", []),
        "events": users_data.get("events", []),
        "assignments": users_data.get("assignments", []),
        "location_counts": users_data.get("location_counts", {}),
        "ov_total_sales": sales_data.get("total_sales", 0),
        "ov_sales_by_location": sales_data.get("sales_by_location", {}),
        "ov_sales_by_location_volunteer": sales_data.get("sales_by_location_volunteer", {}),
        "ov_filter_label": _build_filter_label(filters),
        **filters,
    }


# --------------------------------------------------------------------------- #
# Page (SSR landing)
# --------------------------------------------------------------------------- #

@bp.route("/volunteer-assignment")
@permission_required("volunteer_assignment_view")
def volunteer_assignment():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp

    today_iso = date.today().isoformat()
    filters = _overview_filters(today_iso)
    page_data = _fetch_overview_payload(filters)

    return render_template(
        "volunteer_assignment.html",
        today=today_iso,
        **page_data,
    )


# --------------------------------------------------------------------------- #
# JSON: overview refresh (filter bar) — no reload
# --------------------------------------------------------------------------- #

@bp.route("/api/volunteer-assignment/overview")
@permission_required("volunteer_assignment_view")
def api_volunteer_overview():
    redirect_resp = _require_login()
    if redirect_resp:
        return jsonify({"error": "unauthorized"}), 401

    filters = _overview_filters()
    return jsonify(_fetch_overview_payload(filters))


# --------------------------------------------------------------------------- #
# JSON: create assignments — no reload
# --------------------------------------------------------------------------- #

@bp.route("/volunteers_assignments", methods=["POST"])
@permission_required("volunteer_assignment_view")
def volunteers_assignments():
    redirect_resp = _require_login()
    if redirect_resp:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    rows = [
        {
            "volunteer": r.get("volunteer"),
            "location": r.get("location"),
            "event": r.get("event") or None,
            "date": r.get("date"),
        }
        for r in data.get("rows", [])
        if r.get("volunteer") and r.get("location") and r.get("date")
    ]

    if not rows:
        return jsonify({"error": "No valid assignment rows submitted."}), 400

    try:
        result = post_json(_base_url(), "/api/volunteers/assignment", json={"rows": rows})
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502

    created = result if isinstance(result, list) else (result or {}).get("created", [])
    return jsonify({"created": created, "count": len(created)})


# --------------------------------------------------------------------------- #
# JSON: bulk delete — no reload
# --------------------------------------------------------------------------- #

@bp.route("/volunteer_assignments_bulk_delete", methods=["POST"])
@permission_required("volunteer_assignment_view")
def volunteer_assignments_bulk_delete():
    redirect_resp = _require_login()
    if redirect_resp:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    assignment_ids = [int(i) for i in data.get("assignment_ids", []) if str(i).strip().isdigit()]

    if not assignment_ids:
        return jsonify({"error": "No assignments selected."}), 400

    try:
        result = post_json(
            _base_url(),
            "/api/users/volunteers/assignments/bulk-delete",
            params={"ids": assignment_ids},
        )
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify({"deleted": (result or {}).get("deleted", 0), "ids": assignment_ids})


# --------------------------------------------------------------------------- #
# JSON: master data (location / event) — no reload
# --------------------------------------------------------------------------- #

@bp.route("/api/master-data/locations", methods=["POST"])
@permission_required("master_data_write")
def api_add_location():
    redirect_resp = _require_login()
    if redirect_resp:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Location name is required."}), 400

    try:
        # ASSUMPTION: mirrors the old /master-data/add-location endpoint,
        # confirm the exact path/shape against your books service.
        result = post_json(_base_url_books(), "/api/master-data/locations", json={"name": name})
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(result)


@bp.route("/api/master-data/events", methods=["POST"])
@permission_required("master_data_write")
def api_add_event():
    redirect_resp = _require_login()
    if redirect_resp:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Event name is required."}), 400

    try:
        # ASSUMPTION: mirrors the old /master-data/add-event endpoint,
        # confirm the exact path/shape against your books service.
        result = post_json(_base_url_books(), "/api/master-data/events", json={"name": name})
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(result)