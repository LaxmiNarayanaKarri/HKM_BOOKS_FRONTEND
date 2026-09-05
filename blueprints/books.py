"""
'books' blueprint -> Books service (http://localhost:8001).

I don't have the source for catalog.py / dashboard.py / sell.py /
backup.py / inward_stock.py / master_data.py yet, so every path below
is a PLACEHOLDER guess, clearly marked. The plumbing (Flask route ->
requests call -> template) follows the exact same pattern as
blueprints/users.py, which IS wired to your real contract -- copy that
pattern when you fill these in, or send me the router files and I'll
finish it the same way I did users.py.

Every route degrades gracefully: if the backend call fails (wrong path,
service down, etc.) it flashes the error and still renders the page
with empty/zeroed data instead of crashing, so you can click through
the whole app right now and see exactly which calls need fixing.
"""

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for, Response
from services.api_client import BackendError, get_file, get_json, parallel_get_json, post_form, post_json
from services.auth import permission_required

bp = Blueprint("books", __name__)


def _base_url():
    return current_app.config["BOOK_SERVICE_URL"]

def _base_url_admin():
    return current_app.config["USER_SERVICE_URL"]


def _require_login():
    if "username" not in session:
        return redirect(url_for("users.login"))
    return None


def _is_admin():
    return session.get("role") == "admin"


def _empty_filter_set():
    empty = {"date_from": "", "date_to": "", "seller": "all", "event": "all"}
    return {p: dict(empty) for p in ("", "dist_", "books_", "inv_")}


# ------------------------------------------------------------- dashboard ---

@bp.route("/dashboard")
@permission_required("dashboard_view")
def dashboard():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp

    is_ajax = request.args.get("ajax") == "1"

    try:
        data = get_json(_base_url(), "/api/dashboard", params=request.args)
    except BackendError as exc:
        if is_ajax:
            return jsonify(ok=False, message=f"Could not load the dashboard: {exc.detail}"), 502
        flash(f"Could not load the dashboard: {exc.detail}", "error")
        data = {
            "kpis": {"qty": 0, "cost": 0, "revenue": 0},
            "net_pl": 0,
            "pl_pct": 0,
            "total_available": 0,
            "leaderboard": [],
            "my_top_books": [],
            "inventory": [],
            "filters": {"date_from": "", "date_to": "", "seller": "all", "event": "all"},
            "sellers": [],
            "events": [],
            "window_label": "All time",
            "is_admin": session.get("role") == "admin",
        }

    if is_ajax:
        # Same payload the template consumes — the frontend patches
        # only the section whose filter form triggered this call.
        return jsonify(ok=True, **data)

    return render_template(
        "home.html",
        is_admin=data.get("is_admin", False),
        window_label=data.get("window_label", "All time"),
        filters=data.get("filters", {}),
        sellers=data.get("sellers", []),
        events=data.get("events", []),
        kpis=data.get("kpis", {}),
        net_pl=data.get("net_pl", 0),
        pl_pct=data.get("pl_pct", 0),
        total_available=data.get("total_available", 0),
        leaderboard=data.get("leaderboard", []),
        my_top_books=data.get("my_top_books", []),
        inventory=data.get("inventory", []),
    )

@bp.route("/master-data/threshold", methods=["POST"])
@permission_required("master_data_write")
def master_data_update_threshold():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp

    is_ajax = request.args.get("ajax") == "1"

    title = request.form.get("title", "").strip()
    try:
        threshold = int(request.form.get("threshold", "0"))
    except ValueError:
        threshold = 0

    try:
        result = post_json(
            _base_url(),
            "/api/master-data/books/threshold",
            json={"title": title, "threshold": threshold},
        )
        message = result.get("message", f'Threshold for "{title}" updated.')

        if is_ajax:
            # Backend only updates the threshold and doesn't echo back
            # stock/low-stock info (`book` comes back null) — so we only
            # confirm the save, we don't try to patch other row values.
            return jsonify(ok=True, message=message, title=title, threshold=threshold)
        flash(message, "success")

    except BackendError as exc:
        message = f"Could not update threshold: {exc.detail}"
        if is_ajax:
            return jsonify(ok=False, message=message), 502
        flash(message, "error")

    return redirect(url_for("books.dashboard", **request.args))


# ------------------------------------------------------------ sell entry ---

@bp.route("/sell-entry", methods=["GET", "POST"])
@permission_required("sell_entry_write")
def sell_entry():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp

    is_ajax = request.args.get("ajax") == "1"

    if request.method == "POST":
        titles = request.form.getlist("title[]")
        qtys = request.form.getlist("qty[]")
        costs = request.form.getlist("cost_price[]")
        sells = request.form.getlist("sell_price[]")
        items = [
            {"title": t, "qty": q, "cost_price": c, "sell_price": s}
            for t, q, c, s in zip(titles, qtys, costs, sells)
            if t
        ]
        payload = {
            "date": request.form.get("date"),
            "location": request.form.get("location"),
            "event": request.form.get("event"),
            "items": items,
        }
        try:
            # PLACEHOLDER: POST /api/sell
            result = post_json(_base_url(), "/api/sell", json=payload)
            message = result.get("message", "Sale recorded.")
            if is_ajax:
                return jsonify(ok=True, message=message)
            flash(message, "success")
        except BackendError as exc:
            if is_ajax:
                return jsonify(ok=False, message=str(exc)), 502
            flash(f"Sell entry: {exc}", "danger")
        return redirect(url_for("books.sell_entry"))

    # -- GET: filters -----------------------------------------------------
    se_user = (request.args.get("se_user") or "all").strip() or "all"
    if session.get("role") != "admin":
        se_user = session.get("username", "all")
    se_event = (request.args.get("se_event") or "all").strip() or "all"
    se_date_from = (request.args.get("se_date_from") or "").strip()
    se_date_to = (request.args.get("se_date_to") or "").strip()
    se_location = (request.args.get("se_location") or "all").strip() or "all"

    sale_filters = {
        "user": se_user,
        "event": se_event,
        "date_from": se_date_from,
        "date_to": se_date_to,
        "location": se_location
    }

    context = dict(
        locations=[],
        book_titles=[],
        my_sales=[],
        book_stock={},
        book_cost={},
        users=[],
        sale_filters=sale_filters,
    )

    # /api/sell (page data) and /api/users/get_all (for recorded-by
    # enrichment) don't depend on each other's result, so fire both
    # concurrently instead of waiting on /api/sell before even starting
    # the users call.
    sell_data, users_list = parallel_get_json([
        (_base_url(), "/api/sell", {"params": {
            "se_user": se_user,
            "se_event": se_event,
            "se_date_from": se_date_from,
            "se_date_to": se_date_to,
            "se_location": se_location,
        }}),
        (_base_url_admin(), "/api/users/get_all", {}),
    ])

    if isinstance(sell_data, BackendError):
        # /api/sell is the primary data source for this page -- same
        # fatal behavior as before if it fails.
        if is_ajax:
            return jsonify(ok=False, message=str(sell_data)), 502
        flash(f"Sell entry: {sell_data}", "danger")
    elif sell_data:
        if isinstance(users_list, BackendError):
            # Users list is only used for enrichment elsewhere -- don't
            # fail the whole page over it, just degrade to an empty list.
            users_list = []
        sell_data["users"] = users_list
        context.update(sell_data)
        context["sale_filters"] = sale_filters  # keep the normalized version, not whatever the API echoes back

    if is_ajax:
        # book_stock/book_cost included so the frontend can refresh
        # Available Stock / Cost Price in place after a sale or a filter
        # change, not just "My Recent Entries" -- see refreshTable() in
        # sell_entry.html.
        return jsonify(
            ok=True,
            my_sales=context["my_sales"],
            book_stock=context.get("book_stock", {}),
            book_cost=context.get("book_cost", {}),
        )

    return render_template("sell_entry.html", **context)


@bp.route("/book-requests", methods=["POST"])
@permission_required("book_request_create")
def create_book_request():
    payload = request.get_json(force=True) or {}
    try:
        result = post_json(_base_url(), "/api/book-requests", json=payload)
    except BackendError as exc:
        return jsonify({"ok": False, "message": f"Book request failed: {exc}"}), exc.status_code if exc.status_code < 500 else 502
    return jsonify({"ok": True, "request": result})


@bp.route("/book-requests/mine", methods=["GET"])
@permission_required("book_request_create")
def my_book_requests():
    try:
        return jsonify(get_json(_base_url(), "/api/book-requests/mine") or [])
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502


@bp.route("/book-requests/history", methods=["GET"])
@permission_required("book_request_history")
def book_request_history():
    try:
        return jsonify(get_json(_base_url(), "/api/book-requests/history") or [])
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502


@bp.route("/book-requests/<request_id>/approve", methods=["POST"])
@permission_required("book_request_history")
def approve_book_request(request_id):
    try:
        result = post_json(_base_url(), f"/api/book-requests/{request_id}/approve", json={})
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)

@bp.route("/sell-entry/export")
@permission_required("admin_tools")
def export_sell_entries():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    try:
        # PLACEHOLDER: GET /api/sell/export
        resp = get_file(_base_url(), "/api/sell/export")
    except BackendError as exc:
        flash(f"Export: {exc}", "danger")
        return redirect(url_for("books.sell_entry"))
    return _xlsx_response(resp, "sell_entries.xlsx")


def _enrich_recorded_by(purchases, users_list):
    """Attach recorded_by_name to each purchase row using the users list."""
    users_by_username = {u["username"]: u for u in (users_list or [])}
    for p in purchases:
        if not p.get("recorded_by_name"):
            u = users_by_username.get(p.get("recorded_by", ""))
            p["recorded_by_name"] = u["username"] if u else p.get("recorded_by", "—")
    return purchases


@bp.route("/inward-stock", methods=["GET"])
@permission_required("inward_stock_write")
def inward_stock():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp

    is_ajax     = request.args.get("ajax") == "1"
    want_master = request.args.get("master") == "1"

    context = dict(
        sources=[], book_catalog=[], languages=[], categories=[],
        recorders=[], purchased_titles=[], recent_purchases=[],
        purchase_filters={"recorded_by": "all", "book": "all", "date_from": "", "date_to": ""},
    )

    # Same independent-call shape as sell_entry(): /api/inward-stock and
    # /api/users/get_all don't depend on each other, so run them
    # concurrently instead of one after the other.
    data, users_list = parallel_get_json([
        (_base_url(), "/api/inward-stock", {"params": request.args.to_dict(flat=True)}),
        (_base_url_admin(), "/api/users/get_all", {}),
    ])

    if isinstance(data, BackendError):
        # /api/inward-stock is the primary data source -- same fatal
        # behavior as before if it fails.
        if is_ajax:
            return jsonify({"ok": False, "message": str(data)}), 500
        flash(f"Inward stock: {data}", "danger")
        return render_template("inward_stock.html", **context)

    if isinstance(users_list, BackendError):
        # Only used for the recorded-by-name enrichment -- degrade
        # gracefully instead of failing the whole page over it.
        users_list = []

    if data:
        data["users"] = users_list
        context.update(data)

    if is_ajax:
        if want_master:
            # Feeds refreshMasterData() on the frontend — this is what keeps
            # the Add New Book modal's Language/Category selects in sync.
            return jsonify({
                "ok": True,
                "book_catalog": context.get("book_catalog") or [],
                "sources":      context.get("sources") or [],
                "languages":    context.get("languages") or [],
                "categories":   context.get("categories") or [],
            })
        purchases = _enrich_recorded_by(context.get("recent_purchases") or [], context.get("users"))
        return jsonify({"ok": True, "recent_purchases": purchases})

    return render_template("inward_stock.html", **context)


@bp.route("/inward-stock", methods=["POST"])
@permission_required("inward_stock_write")
def inward_stock_submit():
    """Handle a new purchase submission (form POST or AJAX)."""
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp

    is_ajax = request.args.get("ajax") == "1"

    book_ids = request.form.getlist("book_id[]")
    qtys     = request.form.getlist("qty[]")
    costs    = request.form.getlist("cost[]")

    try:
        items = [
            {"book_id": int(b), "qty": int(q), "cost_price": float(co)}
            for b, q, co in zip(book_ids, qtys, costs)
            if b and q and co
        ]
        payload = {
            "purchase_date": request.form.get("purchase_date"),
            "source_id":     int(request.form.get("source", "").strip()),
            "items":         items,
        }
    except (TypeError, ValueError) as exc:
        message = f"Invalid form data: {exc}"
        if is_ajax:
            return jsonify({"ok": False, "message": message}), 400
        flash(message, "danger")
        return redirect(url_for("books.inward_stock"))

    try:
        result  = post_json(_base_url(), "/api/inward-stock", json=payload)
        message = result.get("message", "Purchase recorded.")
    except BackendError as exc:
        if is_ajax:
            return jsonify({"ok": False, "message": str(exc)}), 400
        flash(f"Inward stock: {exc}", "danger")
        return redirect(url_for("books.inward_stock"))

    if is_ajax:
        return jsonify({"ok": True, "message": message})

    flash(message, "success")
    return redirect(url_for("books.inward_stock"))

@bp.route("/inward-stock/export")
@permission_required("admin_tools")  
def export_inward_stock():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    try:
        # PLACEHOLDER: GET /api/inward-stock/export
        resp = get_file(_base_url(), "/api/inward-stock/export", params=request.args.to_dict(flat=True))
    except BackendError as exc:
        flash(f"Export: {exc}", "danger")
        return redirect(url_for("books.inward_stock"))
    return _xlsx_response(resp, "inward_stock.xlsx")


# ------------------------------------------------------------ master data ---

@bp.route("/master-data")
@permission_required("master_data_write")
def master_data():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp

    context = dict(books=[], categories=[], languages=[], locations=[], events=[])
    try:
        # PLACEHOLDER: GET /api/master-data
        data = get_json(_base_url(), "/api/master-data")
        if data:
            context.update(data)
    except BackendError as exc:
        flash(f"Master data: {exc}", "danger")

    return render_template("master_data.html", **context)


def _master_data_add(subpath, field_from_form, redirect_flash_label):
    payload = {k: request.form.get(k) for k in field_from_form}
    is_ajax = request.args.get("ajax") == "1"

    try:
        result  = post_json(_base_url(), f"/api/master-data/{subpath}", json=payload)
        message = result.get("message", f"{redirect_flash_label} added.")
    except BackendError as exc:
        message = f"{redirect_flash_label}: {exc}"
        if is_ajax:
            return jsonify({"message": message}), 400
        flash(message, "danger")
        return redirect(request.referrer or url_for("books.dashboard"))

    if is_ajax:
        # Frontend reads data.name to know what to select after reload.
        return jsonify({"message": message, "name": payload.get("name") or payload.get("title")}), 201

    flash(message, "success")
    return redirect(request.referrer or url_for("books.dashboard"))



@bp.route("/master-data/books", methods=["POST"])
@permission_required("master_data_write")
def master_data_add_book():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    return _master_data_add("books", ["title", "short_title", "threshold","language","category"], "Book")


@bp.route("/master-data/categories", methods=["POST"])
@permission_required("master_data_write")
def master_data_add_category():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    return _master_data_add("categories", ["name"], "Category")


@bp.route("/master-data/languages", methods=["POST"])
@permission_required("master_data_write")
def master_data_add_language():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    return _master_data_add("languages", ["name"], "Language")


@bp.route("/master-data/locations", methods=["POST"])
@permission_required("master_data_write")
def master_data_add_location():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    return _master_data_add("locations", ["name"], "Location")


@bp.route("/master-data/events", methods=["POST"])
@permission_required("master_data_write")
def master_data_add_event():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    return _master_data_add("events", ["name"], "Event")


@bp.route("/master-data/sources", methods=["POST"])
@permission_required("master_data_write")
def master_data_add_source():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    return _master_data_add("sources", ["name"], "Source")

# @bp.route("/master-data/threshold", methods=["POST"])
# def master_data_update_threshold():
#     redirect_resp = _require_login()
#     if redirect_resp:
#         return redirect_resp
#     payload = {"title": request.form.get("title"), "threshold": request.form.get("threshold")}
#     try:
#         # PLACEHOLDER: POST /api/master-data/books/threshold
#         result = post_json(_base_url(), "/api/master-data/books/threshold", json=payload)
#         flash(result.get("message", "Threshold updated."), "success")
#     except BackendError as exc:
#         flash(f"Threshold: {exc}", "danger")
#     return redirect(request.referrer or url_for("books.dashboard"))


# ------------------------------------------------------------------ backup ---

# @bp.route("/backup")
# @permission_required("backup")
# def backup():
#     redirect_resp = _require_login()
#     if redirect_resp:
#         return redirect_resp

#     days = []
#     try:
#         # PLACEHOLDER: GET /api/backup -> {"days": [{"date":..., "has_records":...}]}
#         data = get_json(_base_url(), "/api/backup") or {}
#         days = data.get("days", [])
#     except BackendError as exc:
#         flash(f"Backup: {exc}", "danger")

#     return render_template("backup.html", days=days)


# @bp.route("/backup/<day>/download")
# @permission_required("backup")
# def backup_download(day):
#     redirect_resp = _require_login()
#     if redirect_resp:
#         return redirect_resp
#     try:
#         # PLACEHOLDER: GET /api/backup/{day}/export
#         resp = get_file(_base_url(), f"/api/backup/{day}/export")
#     except BackendError as exc:
#         flash(f"Backup download: {exc}", "danger")
#         return redirect(url_for("books.backup"))
#     return _xlsx_response(resp, f"backup_{day}.xlsx")


# ------------------------------------------------------------------ upload ---

@bp.route("/upload", methods=["GET", "POST"])
@permission_required("master_data_write")
def upload():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp

    if request.method == "POST":
        file = request.files.get("file")
        if not file or not file.filename:
            flash("Choose a file first.", "danger")
            return redirect(url_for("books.upload"))
        try:
            # PLACEHOLDER: POST /api/catalog/upload (multipart)
            result = post_form(
                _base_url(), "/api/catalog/upload",
                files={"file": (file.filename, file.stream, file.mimetype)},
            )
            flash(result.get("message", "Upload imported."), "success")
        except BackendError as exc:
            flash(f"Upload: {exc}", "danger")
        return redirect(url_for("books.upload"))

    expected_columns = ["Date", "Title", "Category", "Seller", "Qty", "Cost Price", "Sell Price"]
    try:
        # PLACEHOLDER: GET /api/catalog/upload/columns
        data = get_json(_base_url(), "/api/catalog/upload/columns")
        if data and data.get("columns"):
            expected_columns = data["columns"]
    except BackendError:
        pass  # fine to keep the default list above

    return render_template("upload.html", expected_columns=expected_columns)


@bp.route("/upload/sample")
@permission_required("master_data_write")
def upload_sample():
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    try:
        # PLACEHOLDER: GET /api/catalog/upload/sample
        resp = get_file(_base_url(), "/api/catalog/upload/sample")
    except BackendError as exc:
        flash(f"Sample file: {exc}", "danger")
        return redirect(url_for("books.upload"))
    return _xlsx_response(resp, "sample_upload.xlsx")


# ------------------------------------------------------------------ exports ---

@bp.route("/dashboard/export/leaderboard")
@permission_required("admin_tools")
def export_leaderboard():
    return _dashboard_export("/api/dashboard/export/leaderboard", "leaderboard.xlsx")


@bp.route("/dashboard/export/top-books")
@permission_required("admin_tools")
def export_top_books():
    return _dashboard_export("/api/dashboard/export/top-books", "top_books.xlsx")


@bp.route("/dashboard/export/inventory")
@permission_required("admin_tools")
def export_inventory():
    return _dashboard_export("/api/dashboard/export/inventory", "inventory.xlsx")


def _dashboard_export(path, filename):
    redirect_resp = _require_login()
    if redirect_resp:
        return redirect_resp
    try:
        # PLACEHOLDER export path -- see function name for which table.
        resp = get_file(_base_url(), path, params=request.args.to_dict(flat=True))
    except BackendError as exc:
        flash(f"Export: {exc}", "danger")
        return redirect(url_for("books.dashboard"))
    return _xlsx_response(resp, filename)


def _xlsx_response(resp, default_filename):
    return Response(
        resp.content,
        mimetype=resp.headers.get(
            "Content-Type",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        headers={
            "Content-Disposition": resp.headers.get(
                "Content-Disposition", f'attachment; filename="{default_filename}"'
            )
        },
    )