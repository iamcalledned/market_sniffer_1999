from __future__ import annotations

from flask import Flask, render_template

from market_sniffer.web.extensions import close_db_session


# Define custom application errors that indicate setup/data issues
class WebError(Exception):
    status_code = 500
    title = "System Error"
    command = ""


class DatabaseUnavailable(WebError):
    status_code = 503
    title = "Database Unavailable"
    command = "python -m market_sniffer.cli db init"


class EmptyDatabase(WebError):
    status_code = 500
    title = "Database is Empty"
    command = "python -m market_sniffer.cli backfill --profile core --months 24"


class CanonicalDataMissing(WebError):
    status_code = 500
    title = "Canonical Data Missing"
    command = "python -m market_sniffer.cli backfill --profile core --months 24"


class MetricsNotCalculated(WebError):
    status_code = 500
    title = "Metrics Not Calculated"
    command = "python -m market_sniffer.cli metrics backfill --profile core"


class EvidenceNotCalculated(WebError):
    status_code = 500
    title = "Evidence Not Evaluated"
    command = "python -m market_sniffer.cli evidence evaluate --as-of 2026-06-25"


class ChartMetricNotFound(WebError):
    status_code = 404
    title = "Chart Target Not Found"
    command = "python -m market_sniffer.cli metrics backfill --profile core"


def create_app(config: dict | None = None) -> Flask:
    """Flask application factory."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # Set configuration values
    app.config["FIXTURE"] = config.get("fixture", False) if config else False

    # Clean up DB sessions after requests
    app.teardown_appcontext(close_db_session)

    # Register routes
    from market_sniffer.web.routes.api import api_bp
    from market_sniffer.web.routes.charts import charts_bp
    from market_sniffer.web.routes.dashboard import dashboard_bp
    from market_sniffer.web.routes.quotes import quotes_bp

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(charts_bp)
    app.register_blueprint(api_bp)

    # Register error handlers for custom setup errors
    @app.errorhandler(DatabaseUnavailable)
    @app.errorhandler(EmptyDatabase)
    @app.errorhandler(CanonicalDataMissing)
    @app.errorhandler(MetricsNotCalculated)
    @app.errorhandler(EvidenceNotCalculated)
    @app.errorhandler(ChartMetricNotFound)
    def handle_setup_error(error: WebError):
        return (
            render_template(
                "errors/setup.html",
                title=error.title,
                message=str(error),
                command=error.command,
            ),
            error.status_code,
        )

    # Standard errors
    @app.errorhandler(404)
    def page_not_found(e):
        return (
            render_template(
                "errors/setup.html",
                title="Page Not Found",
                message="The requested URL was not found on this server.",
                command="",
            ),
            404,
        )

    @app.errorhandler(500)
    def internal_server_error(e):
        return (
            render_template(
                "errors/setup.html",
                title="Internal Server Error",
                message="An unexpected error occurred. Please verify your database configuration.",
                command="python -m market_sniffer.cli status",
            ),
            500,
        )

    return app
