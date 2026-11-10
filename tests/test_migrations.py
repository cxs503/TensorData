from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    database_path = tmp_path / "migration-test.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("TENSORDATA_DATABASE_URL", database_url)

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    try:
        table_names = set(inspect(engine).get_table_names())
        assert {
            "alembic_version",
            "data_assets",
            "data_artifacts",
            "datasets",
            "dataset_versions",
            "provenance_records",
        }.issubset(table_names)

        command.downgrade(config, "base")
        assert inspect(engine).get_table_names() == ["alembic_version"]

        # migration 0002 (quality reports) round-trips on its own
        command.upgrade(config, "head")
        quality_columns = {
            column["name"] for column in inspect(engine).get_columns("quality_reports")
        }
        assert {
            "id",
            "artifact_id",
            "artifact_sha256",
            "profile",
            "ruleset_version",
            "status",
            "summary_json",
            "findings_json",
            "executed_by",
            "created_at",
        }.issubset(quality_columns)

        command.downgrade(config, "0001")
        assert "quality_reports" not in inspect(engine).get_table_names()
        command.upgrade(config, "head")
        assert "quality_reports" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
