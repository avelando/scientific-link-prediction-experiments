"""Tests for credential hygiene: log redaction, gitignore, cache URL sanitization."""

import logging
from pathlib import Path

from slpe.logging_utils import RedactingFilter, redact

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_redact_api_key_and_mailto():
    url = "https://api.openalex.org/works?filter=x&api_key=SECRET123&mailto=me@x.org"
    out = redact(url)
    assert "SECRET123" not in out
    assert "me@x.org" not in out
    assert "api_key=REDACTED" in out and "mailto=REDACTED" in out


def test_redact_handles_dashed_and_cased_keys():
    assert "k" not in redact("API-KEY=k")
    assert "v" not in redact("Api_Key=v")


def test_redacting_filter_rewrites_record_message():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1,
                            "GET url?api_key=TOPSECRET", None, None)
    RedactingFilter().filter(rec)
    assert "TOPSECRET" not in rec.getMessage()


def test_redacting_filter_rewrites_args():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1,
                            "fetched %s", ("url?mailto=a@b.org",), None)
    RedactingFilter().filter(rec)
    assert "a@b.org" not in rec.getMessage()


def test_gitignore_excludes_env():
    gi = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gi


def test_env_example_has_no_real_key():
    ex = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    # The example must leave the key blank.
    for line in ex.splitlines():
        if line.strip().startswith("OPENALEX_API_KEY="):
            assert line.strip() == "OPENALEX_API_KEY="
