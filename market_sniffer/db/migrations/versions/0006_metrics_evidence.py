"""metrics and evidence foundation

Revision ID: 0006_metrics_evidence
Revises: 0005_yahoo_legacy_price_basis
Create Date: 2026-06-26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_metrics_evidence"
down_revision = "0005_yahoo_legacy_price_basis"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("metric_definitions"):
        return
    op.create_table(
        "metric_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("metric_code", sa.String(120), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("formula_version", sa.String(40), nullable=False),
        sa.Column("frequency", sa.String(40), nullable=False),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_metric_definitions_metric_code", "metric_definitions", ["metric_code"], unique=True)
    op.create_index("ix_metric_definitions_category", "metric_definitions", ["category"])
    op.create_index("ix_metric_definitions_formula_version", "metric_definitions", ["formula_version"])
    op.create_index("ix_metric_definitions_frequency", "metric_definitions", ["frequency"])
    op.create_index("ix_metric_definitions_enabled", "metric_definitions", ["enabled"])

    op.create_table(
        "metric_calculation_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile", sa.String(80), nullable=False),
        sa.Column("as_of_start", sa.Date(), nullable=True),
        sa.Column("as_of_end", sa.Date(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("started_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metrics_attempted", sa.Integer(), nullable=False),
        sa.Column("metrics_succeeded", sa.Integer(), nullable=False),
        sa.Column("metrics_skipped", sa.Integer(), nullable=False),
        sa.Column("metrics_failed", sa.Integer(), nullable=False),
        sa.Column("details_json", sa.JSON(), nullable=False),
    )
    op.create_index("ix_metric_calculation_runs_profile", "metric_calculation_runs", ["profile"])
    op.create_index("ix_metric_calculation_runs_as_of_start", "metric_calculation_runs", ["as_of_start"])
    op.create_index("ix_metric_calculation_runs_as_of_end", "metric_calculation_runs", ["as_of_end"])
    op.create_index("ix_metric_calculation_runs_status", "metric_calculation_runs", ["status"])
    op.create_index("ix_metric_calculation_runs_started_at_utc", "metric_calculation_runs", ["started_at_utc"])

    op.create_table(
        "metric_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("metric_definition_id", sa.Integer(), sa.ForeignKey("metric_definitions.id"), nullable=False),
        sa.Column("calculation_run_id", sa.Integer(), sa.ForeignKey("metric_calculation_runs.id"), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("value_numeric", sa.Numeric(28, 10), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("quality_status", sa.String(40), nullable=False),
        sa.Column("quality_details_json", sa.JSON(), nullable=False),
        sa.Column("formula_version", sa.String(40), nullable=False),
        sa.Column("source_lineage_json", sa.JSON(), nullable=False),
        sa.Column("input_window_start", sa.Date(), nullable=True),
        sa.Column("input_window_end", sa.Date(), nullable=True),
        sa.Column("effective_source_date", sa.Date(), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "metric_definition_id",
            "as_of_date",
            "formula_version",
            name="uq_metric_observation_formula",
        ),
    )
    op.create_index("ix_metric_observations_metric_definition_id", "metric_observations", ["metric_definition_id"])
    op.create_index("ix_metric_observations_calculation_run_id", "metric_observations", ["calculation_run_id"])
    op.create_index("ix_metric_observations_as_of_date", "metric_observations", ["as_of_date"])
    op.create_index("ix_metric_observations_quality_status", "metric_observations", ["quality_status"])
    op.create_index("ix_metric_observations_formula_version", "metric_observations", ["formula_version"])
    op.create_index("ix_metric_observations_input_window_start", "metric_observations", ["input_window_start"])
    op.create_index("ix_metric_observations_input_window_end", "metric_observations", ["input_window_end"])
    op.create_index("ix_metric_observations_effective_source_date", "metric_observations", ["effective_source_date"])

    op.create_table(
        "evidence_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_code", sa.String(160), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("metric_definition_id", sa.Integer(), sa.ForeignKey("metric_definitions.id"), nullable=False),
        sa.Column("metric_observation_id", sa.Integer(), sa.ForeignKey("metric_observations.id"), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("rule_version", sa.String(40), nullable=False),
        sa.Column("headline", sa.String(240), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("value_numeric", sa.Numeric(28, 10), nullable=True),
        sa.Column("prior_value_numeric", sa.Numeric(28, 10), nullable=True),
        sa.Column("threshold_numeric", sa.Numeric(28, 10), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "event_code",
            "metric_definition_id",
            "as_of_date",
            "rule_version",
            name="uq_evidence_event_rule",
        ),
    )
    op.create_index("ix_evidence_events_event_code", "evidence_events", ["event_code"])
    op.create_index("ix_evidence_events_event_type", "evidence_events", ["event_type"])
    op.create_index("ix_evidence_events_severity", "evidence_events", ["severity"])
    op.create_index("ix_evidence_events_metric_definition_id", "evidence_events", ["metric_definition_id"])
    op.create_index("ix_evidence_events_metric_observation_id", "evidence_events", ["metric_observation_id"])
    op.create_index("ix_evidence_events_as_of_date", "evidence_events", ["as_of_date"])
    op.create_index("ix_evidence_events_rule_version", "evidence_events", ["rule_version"])


def downgrade() -> None:
    op.drop_table("evidence_events")
    op.drop_table("metric_observations")
    op.drop_table("metric_calculation_runs")
    op.drop_table("metric_definitions")
