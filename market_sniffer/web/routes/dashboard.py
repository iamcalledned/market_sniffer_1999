from __future__ import annotations

from flask import Blueprint, render_template

from market_sniffer.services.dashboard.service import DashboardService
from market_sniffer.web.extensions import get_db_session

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    """Renders the main read-only dashboard briefing page."""
    session = get_db_session()
    service = DashboardService(session)
    view_model = service.build_dashboard_view_model()
    return render_template("dashboard/index.html", vm=view_model)
