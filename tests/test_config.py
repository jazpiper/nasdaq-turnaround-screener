from __future__ import annotations

from screener.config import get_settings


ORACLE_ENV_NAMES = (
    "ORACLE_DB_USER",
    "ORACLE_DB_PASSWORD",
    "ORACLE_DB_CONNECT_STRING",
    "SCREENER_ORACLE_SQL_USER",
    "SCREENER_ORACLE_SQL_PASSWORD",
    "SCREENER_ORACLE_SQL_CONNECT_STRING",
)


def test_get_settings_reads_documented_oracle_env_names(monkeypatch, tmp_path) -> None:
    for name in ORACLE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ORACLE_DB_USER", "doc_user")
    monkeypatch.setenv("ORACLE_DB_PASSWORD", "doc_password")
    monkeypatch.setenv("ORACLE_DB_CONNECT_STRING", "doc_connect")

    settings = get_settings(openclaw_secrets_path=tmp_path / "missing-secrets.json")

    assert settings.oracle_sql_user == "doc_user"
    assert settings.oracle_sql_password == "doc_password"
    assert settings.oracle_sql_connect_string == "doc_connect"


def test_get_settings_reads_legacy_screener_oracle_aliases(monkeypatch, tmp_path) -> None:
    for name in ORACLE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SCREENER_ORACLE_SQL_USER", "alias_user")
    monkeypatch.setenv("SCREENER_ORACLE_SQL_PASSWORD", "alias_password")
    monkeypatch.setenv("SCREENER_ORACLE_SQL_CONNECT_STRING", "alias_connect")

    settings = get_settings(openclaw_secrets_path=tmp_path / "missing-secrets.json")

    assert settings.oracle_sql_user == "alias_user"
    assert settings.oracle_sql_password == "alias_password"
    assert settings.oracle_sql_connect_string == "alias_connect"


def test_get_settings_prefers_documented_oracle_env_over_aliases(monkeypatch, tmp_path) -> None:
    for name in ORACLE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ORACLE_DB_USER", "doc_user")
    monkeypatch.setenv("ORACLE_DB_PASSWORD", "doc_password")
    monkeypatch.setenv("ORACLE_DB_CONNECT_STRING", "doc_connect")
    monkeypatch.setenv("SCREENER_ORACLE_SQL_USER", "alias_user")
    monkeypatch.setenv("SCREENER_ORACLE_SQL_PASSWORD", "alias_password")
    monkeypatch.setenv("SCREENER_ORACLE_SQL_CONNECT_STRING", "alias_connect")

    settings = get_settings(openclaw_secrets_path=tmp_path / "missing-secrets.json")

    assert settings.oracle_sql_user == "doc_user"
    assert settings.oracle_sql_password == "doc_password"
    assert settings.oracle_sql_connect_string == "doc_connect"
