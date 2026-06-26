from __future__ import annotations

from flask import Blueprint, current_app, flash, render_template, request

from market_sniffer.services.quotes.yahoo_quote_service import YahooQuoteService
from market_sniffer.web.extensions import get_db_session

quotes_bp = Blueprint("quotes", __name__, url_prefix="/quotes")


@quotes_bp.route("", methods=["GET"])
def lookup_form():
    """Renders the single-symbol Yahoo quote lookup page."""
    return render_template("quotes/lookup.html", quote=None)


@quotes_bp.route("/lookup", methods=["POST"])
def lookup():
    """Triggers Yahoo quote lookup for a single symbol and renders the details."""
    symbol = request.form.get("symbol", "").strip()
    persist = request.form.get("persist") == "true"

    if not symbol:
        flash("Please enter a symbol.")
        return render_template("quotes/lookup.html", quote=None, error="Symbol cannot be empty.")

    session = get_db_session()
    fixture_mode = current_app.config.get("FIXTURE", False)
    service = YahooQuoteService(session, fixture=fixture_mode)

    try:
        quote = service.lookup_quote(symbol, persist=persist)
        return render_template("quotes/lookup.html", quote=quote)
    except Exception as e:
        return render_template("quotes/lookup.html", quote=None, error=str(e), symbol_value=symbol)
