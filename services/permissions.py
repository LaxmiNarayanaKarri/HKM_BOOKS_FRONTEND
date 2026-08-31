# permissions.py  (place in: flask app/services/, users-service/app/core/,
# books-service/app/core/ — same filename/shape in all three)

"""
Single source of truth for which roles can perform which logical
action. Routes reference the action name, never a raw role list --
so changing who's allowed to do something is a one-line edit here,
not a hunt through every route in three codebases.
"""

ROUTE_PERMISSIONS = {
    "dashboard_view":        ["admin"],
    "user_management":       ["admin"],
    "sell_entry_write":      ["admin", "commander", "volunteer"],
    "inward_stock_write":    ["admin"],
    "volunteer_assignment":  ["admin", "commander"],
    "backup":                ["admin"],
    "catalog_view":          ["admin", "commander", "volunteer"],
    "location_overview":       ["admin", "commander", "volunteer"],
    "master_data_write":        ["admin", "commander", "volunteer"],
    "admin_tools":            ["admin"],
    "volunteer_assignment_view": ["admin", "commander"],
    # add new actions here as you find more routes that need gating --
    # fill in your real role names once you send them over
}


def roles_for(action: str) -> list[str]:
    try:
        return ROUTE_PERMISSIONS[action]
    except KeyError:
        raise KeyError(
            f"No permission entry for action '{action}' — add it to "
            f"ROUTE_PERMISSIONS in permissions.py before gating a route with it."
        )