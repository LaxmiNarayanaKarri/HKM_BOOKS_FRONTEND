from flask import Flask, session

from config import Config


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

    return app


app = create_app()

if __name__ == "__main__":
    import os

    app.run(host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 5000)), debug=True)
