from datetime import datetime
from types import SimpleNamespace
from urllib.parse import quote

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    render_template_string,
    request,
    session,
    url_for,
    Response,
)

from services.api_client import BackendError, get_file, get_json, parallel_get_json, post_json

from services.auth import permission_required
from services.permissions import roles_for


bp = Blueprint("nidhi", __name__)

TEMPLATE = "nidhi_dashboard.html"

# A layout with no logic in it at all -- used only when importing macros out
# of nidhi_dashboard.html for AJAX fragments (see _render_macro below).
# nidhi_dashboard.html extends "layout|default('base.html')": normal page
# loads leave `layout` unset and fall through to the real base.html, but
# fragment renders pass this blank stand-in instead. Without it, Jinja's
# {% import %} would still have to fully execute the extends chain (that's
# just how compiled Jinja templates work), which meant every fragment
# render was silently re-rendering base.html's nav/permission logic with
# none of the session/request context it actually needs -- the cause of
# the "has_permission is undefined" crash.
_BLANK_LAYOUT_SOURCE = (
    "{% block title %}{% endblock %}"
    "{% block page_title %}{% endblock %}"
    "{% block content %}{% endblock %}"
    "{% block scripts %}{% endblock %}"
)

# ----------------------------------------------------------------------
# Fragment rendering
# ----------------------------------------------------------------------
#
# nidhi_dashboard.html defines everything (balances_section,
# transactions_table, my_pending_list, redeem_review_list, plus the
# user_combobox / fund_select helpers they call) as Jinja macros. Rather
# than keeping separate "_xxx_fragment.html" files in sync with that page,
# the AJAX endpoints below import the macros straight out of
# nidhi_dashboard.html via render_template_string and call them directly.
# There is exactly one template file, and the full page and every AJAX
# fragment always render from the same markup.

def _render_macro(macro_call, **context):
    """
    macro_call: e.g. 'nidhi.balances_section(tirtha_amount, contribution_amount, tirtha_updated_at, contribution_updated_at)'
    context: the variables that macro_call's arguments reference.

    Renders by importing macros straight out of nidhi_dashboard.html. Always
    passes `layout` as the blank stand-in (see _BLANK_LAYOUT_SOURCE above)
    so the import never falls through into rendering the real base.html.
    """
    context.setdefault("layout", current_app.jinja_env.from_string(_BLANK_LAYOUT_SOURCE))
    return render_template_string(
        '{%% import "%s" as nidhi with context %%}{{ %s }}' % (TEMPLATE, macro_call),
        **context,
    )


# ----------------------------------------------------------------------
# Service URLs
# ----------------------------------------------------------------------

def _base_url():
    """Books/Nidhi backend service base URL."""
    return current_app.config["BOOK_SERVICE_URL"]


def _user_service_url():
    """Users microservice base URL."""
    return current_app.config["USER_SERVICE_URL"]


def _can_review_redemptions():
    """
    Soft, non-raising equivalent of @permission_required("nidhi_approve") --
    used only to decide whether to render/fetch the admin "Redeem review"
    section. Reads from the same roles_for() lookup the hard decorator
    uses, so it can never drift out of sync with who is actually allowed
    to hit the redemption-review routes.
    """
    return session.get("role") in roles_for("nidhi_approve")



# ----------------------------------------------------------------------
# Users (for the contribute / redeem dropdowns)
# ----------------------------------------------------------------------

def _fetch_users(exclude_user_id=None):
    """
    Calls the Users service's `GET /get_all` and returns a normalized
    list of {"id": ..., "label": ...} dicts for the contribute/redeem
    user-selection dropdowns. Excludes `exclude_user_id` (the current
    user) so nobody can pick themselves as the target. Swallows errors
    to a flash + empty list, since a users-service hiccup shouldn't
    take down the whole dashboard.
    """
    try:
        raw_users = get_json(_user_service_url(), "/api/users/get_all")
    except BackendError:
        current_app.logger.exception("Failed to fetch users from user service")
        flash("Could not load the user list. Try refreshing the page.", "error")
        return []

    users = []
    for u in raw_users or []:
        user_id = u.get("user_id") or u.get("id") or u.get("username")
        if not user_id or user_id == exclude_user_id:
            continue
        label = u.get("full_name") or u.get("name") or u.get("username") or user_id
        users.append({"id": user_id, "label": label})
    return sorted(users, key=lambda u: u["label"].lower())


# ----------------------------------------------------------------------
# Balances parsing
# ----------------------------------------------------------------------

def parse_nidhi_data(record):
    """
    record: a single dict, e.g.
    {'updated_at': '2026-09-01T13:14:53+00:00',
     'tirtha_balance': 850,
     'contribution_balance': 850,
     'user_id': 'laxmi narayana'}
    -- this is what GET /nidhi/balances returns (one user's balances,
    not a list). Returns (tirtha_amount, contribution_amount,
    tirtha_updated_at, contribution_updated_at), or safe defaults if
    empty.
    """
    if not record:
        return 0, 0, None, None

    tirtha_amount = record.get("tirtha_balance", 0) or 0
    contribution_amount = record.get("contribution_balance", 0) or 0

    updated_at_str = record.get("updated_at")
    updated_at = None
    if updated_at_str:
        updated_at = datetime.fromisoformat(updated_at_str)

    return tirtha_amount, contribution_amount, updated_at, updated_at


class _ValueWrapper:
    """
    Minimal stand-in for a Python Enum member. The templates were written
    against ORM objects whose fund_type/type columns are Enums (accessed as
    `t.fund_type.value`), but the Book/Nidhi backend now hands back plain
    JSON where those fields are already bare strings (e.g. "tirtha_nidhi").
    Wrapping them keeps `t.fund_type.value` working without touching the
    templates.
    """
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return str(self.value)


def _normalize_transaction(row):
    """
    Converts one raw transaction/request dict from the Book/Nidhi backend
    into the shape nidhi_dashboard.html's macros expect:
      - created_at: a real `datetime` (backend sends ISO 8601 strings over JSON)
      - fund_type / type: wrapped so `.value` still works (backend sends
        plain strings, not serialized Enum objects)
      - amount / balance_after: coerced to float in case the backend sends
        them as strings (common when the API preserves Decimal precision)
    """
    if row is None:
        return None

    row = dict(row)  # don't mutate the caller's dict

    for key in ("created_at", "decided_at"):
        value = row.get(key)
        if isinstance(value, str):
            row[key] = datetime.fromisoformat(value)

    for key in ("fund_type", "type", "status"):
        val = row.get(key)
        if val is not None and not hasattr(val, "value"):
            row[key] = _ValueWrapper(val)

    for key in ("amount", "balance_after", "tirtha_amount", "contribution_amount"):
        val = row.get(key)
        if isinstance(val, str):
            row[key] = float(val)

    if row.get("tirtha_amount") is None and row.get("contribution_amount") is None:
        row["tirtha_amount"] = row["amount"] if row["fund_type"].value == "tirtha_nidhi" else 0
        row["contribution_amount"] = row["amount"] if row["fund_type"].value == "contribution_nidhi" else 0

    return SimpleNamespace(**row)


def _normalize_transactions(rows):
    return [_normalize_transaction(r) for r in (rows or [])]


def _load_dashboard_data():
    """
    Balances + recent activity + the current user's own pending
    contribution decisions, in one fan-out call. Redemption review is
    fetched separately (see nidhi_dashboard()) since it's admin-only
    and shouldn't 404/error out for everyone else.
    """
    base = _base_url()
    transactions_path = (
        "/nidhi/transactions"
        if _can_review_redemptions()
        else "/nidhi/transactions/mine"
    )
    calls = [
        (base, "/nidhi/balances", {}),
        (base, transactions_path, {"params": {"limit": 10}}),
        (base, "/nidhi/contributions/pending/mine", {}),
    ]
    balances, recent_transactions, my_pending_contributions = parallel_get_json(calls)
    return (
        balances or {},
        _normalize_transactions(recent_transactions),
        _normalize_transactions(my_pending_contributions),
    )


# ----------------------------------------------------------------------
# Dashboard page
# ----------------------------------------------------------------------

@bp.route("/tirtha-nidhi", methods=["GET"])
@permission_required("nidhi_view")
def nidhi_dashboard():
    try:
        balances, recent_transactions, my_pending_contributions = _load_dashboard_data()
    except BackendError as exc:
        flash(f"Could not load the Nidhi dashboard: {exc}", "error")
        balances, recent_transactions, my_pending_contributions = {}, [], []

    tirtha_amount, contribution_amount, tirtha_updated_at, contribution_updated_at = (
        parse_nidhi_data(balances)
    )

    can_review_redemptions = _can_review_redemptions()
    pending_redemptions = []
    if can_review_redemptions:
        try:
            pending_redemptions = _normalize_transactions(
                get_json(_base_url(), "/nidhi/redemptions/pending")
            )
        except BackendError:
            current_app.logger.exception("Failed to fetch pending redemptions")
            flash("Could not load pending redeem requests.", "error")

    users = _fetch_users(exclude_user_id=session.get("username"))

    return render_template(
        TEMPLATE,
        tirtha_amount=tirtha_amount,
        contribution_amount=contribution_amount,
        tirtha_updated_at=tirtha_updated_at,
        contribution_updated_at=contribution_updated_at,
        recent_transactions=recent_transactions,
        my_pending_contributions=my_pending_contributions,
        can_review_redemptions=can_review_redemptions,
        pending_redemptions=pending_redemptions,
        users=users,
    )


# ----------------------------------------------------------------------
# AJAX refresh (balances + recent activity + my-pending / redeem-review badges)
# ----------------------------------------------------------------------

@bp.route("/tirtha-nidhi/refresh", methods=["GET"])
@permission_required("nidhi_view")
def nidhi_refresh():
    try:
        balances, recent_transactions, my_pending_contributions = _load_dashboard_data()
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502

    tirtha_amount, contribution_amount, tirtha_updated_at, contribution_updated_at = (
        parse_nidhi_data(balances)
    )

    balances_html = _render_macro(
        "nidhi.balances_section(tirtha_amount, contribution_amount, tirtha_updated_at, contribution_updated_at)",
        tirtha_amount=tirtha_amount,
        contribution_amount=contribution_amount,
        tirtha_updated_at=tirtha_updated_at,
        contribution_updated_at=contribution_updated_at,
    )
    recent_transactions_html = _render_macro(
        "nidhi.transactions_table(recent_transactions, 'recent-transactions-table', download_name='nidhi-recent-transactions.csv')",
        recent_transactions=recent_transactions,
    )

    redeem_review_count = None
    if _can_review_redemptions():
        try:
            pending_redemptions = get_json(_base_url(), "/nidhi/redemptions/pending") or []
            redeem_review_count = len(pending_redemptions)
        except BackendError:
            current_app.logger.exception("Failed to refresh pending redemptions count")

    payload = {
        "balances_html": balances_html,
        "recent_transactions_html": recent_transactions_html,
        "my_pending_count": len(my_pending_contributions or []),
    }
    if redeem_review_count is not None:
        payload["redeem_review_count"] = redeem_review_count

    return jsonify(payload)


# ----------------------------------------------------------------------
# Full transaction history
# ----------------------------------------------------------------------

@bp.route("/tirtha-nidhi/transactions", methods=["GET"])
@permission_required("nidhi_view")
def nidhi_full_history():
    try:
        transactions_path = (
            "/nidhi/transactions"
            if _can_review_redemptions()
            else "/nidhi/transactions/mine"
        )
        rows = get_json(_base_url(), transactions_path, params={"limit": 500})
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502

    html = _render_macro(
        "nidhi.transactions_table(recent_transactions, 'full-transactions-table', download_name='nidhi-transactions.csv')",
        recent_transactions=_normalize_transactions(rows),
    )
    return jsonify({"html": html})


# ----------------------------------------------------------------------
# Contribute
# ----------------------------------------------------------------------

@bp.route("/tirtha-nidhi/contribute", methods=["POST"])
@permission_required("nidhi_view")
def nidhi_contribute():
    payload = request.get_json(force=True) or {}
    user_id = payload.get("user_id")
    if not user_id:
        return jsonify({"error": "Please select a user."}), 400

    fund_type = payload.get("fund_type")
    if not fund_type:
        return jsonify({"error": "Please select a fund."}), 400

    amount = payload.get("amount")
    if amount is None or amount <= 0:
        return jsonify({"error": "Amount must be greater than 0."}), 400

    body = {
        "user_id": user_id,
        "fund_type": fund_type,
        "amount": amount,
        "note": payload.get("note"),
    }
    try:
        result = post_json(_base_url(), "/nidhi/contribute", json=body)
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(result)


# ----------------------------------------------------------------------
# My pending contributions (recipient decides; nothing editable)
# ----------------------------------------------------------------------

@bp.route("/tirtha-nidhi/contributions/pending", methods=["GET"])
@permission_required("nidhi_view")
def nidhi_my_pending_contributions():
    try:
        rows = get_json(_base_url(), "/nidhi/contributions/pending/mine")
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502

    html = _render_macro(
        "nidhi.my_pending_list(pending)",
        pending=_normalize_transactions(rows),
    )
    return jsonify({"html": html})


@bp.route("/tirtha-nidhi/contributions/<txn_id>/approve", methods=["POST"])
@permission_required("nidhi_view")
def nidhi_contribution_approve(txn_id):
    try:
        result = post_json(_base_url(), f"/nidhi/contributions/{txn_id}/approve", json={})
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)


@bp.route("/tirtha-nidhi/contributions/<txn_id>/reject", methods=["POST"])
@permission_required("nidhi_view")
def nidhi_contribution_reject(txn_id):
    payload = request.get_json(force=True) or {}
    try:
        result = post_json(
            _base_url(), f"/nidhi/contributions/{txn_id}/reject",
            json={"reason": payload.get("reason")},
        )
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)


# ----------------------------------------------------------------------
# Redeem
# ----------------------------------------------------------------------

@bp.route("/tirtha-nidhi/redeem", methods=["POST"])
@permission_required("nidhi_view")
def nidhi_redeem():
    payload = request.get_json(force=True) or {}
    user_id = payload.get("user_id")
    if not user_id:
        return jsonify({"error": "Please select a user."}), 400

    amount = payload.get("amount")
    if amount is None or amount <= 0:
        return jsonify({"error": "Amount must be greater than 0."}), 400

    body = {
        "user_id": user_id,
        "fund_type": payload.get("nidhi_type"),
        "amount": amount,
        "note": payload.get("reason"),
    }
    try:
        result = post_json(_base_url(), "/nidhi/redeem", json=body)
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502

    return jsonify(result)


# ----------------------------------------------------------------------
# Redeem review (admin-only; every field editable before a decision)
# ----------------------------------------------------------------------

@bp.route("/tirtha-nidhi/redemptions/pending", methods=["GET"])
@permission_required("nidhi_approve")
def nidhi_redemptions_pending():
    try:
        rows = get_json(_base_url(), "/nidhi/redemptions/pending")
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502

    users = _fetch_users(exclude_user_id=session.get("username"))
    html = _render_macro(
        "nidhi.redeem_review_list(pending, users)",
        pending=_normalize_transactions(rows),
        users=users,
    )
    return jsonify({"html": html})


@bp.route("/tirtha-nidhi/redemptions/<txn_id>/approve", methods=["POST"])
@permission_required("nidhi_approve")
def nidhi_redemption_approve(txn_id):
    payload = request.get_json(force=True) or {}
    body = {
        k: payload.get(k)
        for k in ("amount", "fund_type", "user_id")
        if payload.get(k) not in (None, "")
    }
    try:
        result = post_json(_base_url(), f"/nidhi/redemptions/{txn_id}/approve", json=body)
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)


@bp.route("/tirtha-nidhi/redemptions/<txn_id>/reject", methods=["POST"])
@permission_required("nidhi_approve")
def nidhi_redemption_reject(txn_id):
    payload = request.get_json(force=True) or {}
    try:
        result = post_json(
            _base_url(), f"/nidhi/redemptions/{txn_id}/reject",
            json={"reason": payload.get("reason")},
        )
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(result)


@bp.route("/tirtha-nidhi/balances/<user_id>", methods=["GET"])
@permission_required("nidhi_view")
def nidhi_user_balances(user_id):
    try:
        balances = get_json(_base_url(), f"/nidhi/balances/{quote(user_id, safe='')}")
    except BackendError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(balances or {})