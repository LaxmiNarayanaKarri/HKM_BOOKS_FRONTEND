from flask import Flask, session

from config import Config
from services.permissions import ROUTE_PERMISSIONS


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    from blueprints.users import bp as users_bp
    from blueprints.books import bp as books_bp

    app.register_blueprint(users_bp)
    app.register_blueprint(books_bp)

    @app.context_processor
    def inject_current_user():
        """Makes `current_user` available in every template (base.html
        reads current_user.role / current_user.name on every page)
        without every route having to pass it explicitly."""
        if "username" in session:
            return {
                "current_user": {
                    "username": session.get("username"),
                    "role": session.get("role"),
                    "name": session.get("name") or session.get("username"),
                }
            }
        return {"current_user": None}

    @app.context_processor
    def inject_permissions():
        """Makes `has_permission('action_name')` available in every
        template (base.html uses it to hide nav links the current
        role can't access). Reads the same ROUTE_PERMISSIONS table
        the @permission_required route decorator checks, so the nav
        and the actual route guard can never drift apart."""
        def has_permission(action):
            role = session.get("role")
            return role is not None and role in ROUTE_PERMISSIONS.get(action, [])
        return {"has_permission": has_permission}

    return app


app = create_app()

if __name__ == "__main__":
    import os

    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 5000)), debug=True)