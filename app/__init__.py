from flask import Flask, render_template

from app.config import configure_paths, configure_session
from app.database import init_database


def create_app(config=None):
    """Build independent applications without a shared database engine."""
    app = Flask(__name__, static_folder="static", template_folder="templates")
    if config is not None:
        app.config.update(config)
    if (app.config.get("AUTH_DISABLED") or app.config.get("WTF_CSRF_ENABLED") is False) and not app.testing:
        raise ValueError("Authentication and CSRF may only be disabled in isolated tests")
    configure_paths(app)
    from tools.offline_lock import init_gate

    init_gate(app)
    configure_session(app)

    from app.main import routes

    app.register_blueprint(routes)
    init_database(app)
    from app.validation import form_value

    app.jinja_env.globals["form_value"] = form_value
    from app.auth import init_auth

    init_auth(app)

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", status=404, message="Nie znaleziono strony lub pliku."), 404

    @app.errorhandler(500)
    def server_error(error):
        return render_template("error.html", status=500, message="Nie udało się wykonać operacji."), 500

    return app
