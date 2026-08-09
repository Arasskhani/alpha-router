"""L2: dangerous opt-in flags are surfaced clearly when enabled."""

from app.main import collect_dangerous_opt_in_flags, _warn_dangerous_opt_in_flags


def test_collect_empty_when_all_false():
    assert collect_dangerous_opt_in_flags() == []


def test_collect_reports_each_enabled_flag():
    flags = collect_dangerous_opt_in_flags(
        allow_legacy_bearer_auth=True,
        allow_ssrf_private_ranges=True,
        allow_insecure_code_subprocess=True,
    )
    names = [name for name, _ in flags]
    assert names == [
        "ALLOW_LEGACY_BEARER_AUTH",
        "ALLOW_SSRF_PRIVATE_RANGES",
        "ALLOW_INSECURE_CODE_SUBPROCESS",
    ]
    assert all(reason for _, reason in flags)


def test_warn_logs_when_flag_enabled(caplog, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main.settings, "allow_legacy_bearer_auth", True)
    monkeypatch.setattr(main.settings, "allow_ssrf_private_ranges", False)
    monkeypatch.setattr(main.settings, "allow_insecure_code_subprocess", False)

    with caplog.at_level("WARNING"):
        _warn_dangerous_opt_in_flags()

    assert any("ALLOW_LEGACY_BEARER_AUTH" in r.message for r in caplog.records)
