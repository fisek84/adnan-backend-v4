from __future__ import annotations

from services.spoken_text import build_spoken_text


def test_spoken_text_shortens_long_url_to_domain_only() -> None:
    t = (
        "Pogledaj ovo: https://example.com/very/long/path/with/many/segments?x=1&y=2 "
        "i reci mi sta mislis."
    )
    out = build_spoken_text(text=t, output_lang="bs", max_chars=2000)
    # Should avoid spelling out the whole URL for speech.
    assert "https://" not in out.spoken_text
    assert "link" in out.spoken_text
    assert "example" in out.spoken_text
    assert "tačka" in out.spoken_text


def test_spoken_text_normalizes_decimal_percent_bhs() -> None:
    t = "Rast je 12.5% i 3,2% danas."
    out = build_spoken_text(text=t, output_lang="bs", max_chars=2000)
    s = out.spoken_text
    assert "12 zarez 5 posto" in s
    assert "3 zarez 2 posto" in s


def test_spoken_text_verbalizes_structured_tokens() -> None:
    t = "Ticket#1234 i putanja A/B-12 su bitni."
    out = build_spoken_text(text=t, output_lang="bs", max_chars=2000)
    s = out.spoken_text
    # # / - should be verbalized inside structured tokens.
    assert "taraba" in s
    assert "kosa crta" in s
    assert "crta" in s


def test_spoken_text_normalizes_numbered_lists_bhs() -> None:
    t = "1. Prvo\n2) Drugo\n3. Trece"
    out = build_spoken_text(text=t, output_lang="bs", max_chars=2000)
    s = out.spoken_text
    assert "Stavka 1," in s
    assert "Stavka 2," in s
    assert "Stavka 3," in s


def test_spoken_text_normalizes_arrow_bhs() -> None:
    t = "A->B"
    out = build_spoken_text(text=t, output_lang="bs", max_chars=2000)
    assert "A na B" in out.spoken_text


def test_spoken_text_normalizes_slash_dates_bhs() -> None:
    # Regression: slash dates were previously treated as structured tokens and read as "kosa crta".
    t = "Rok je 03/20/2026. Alternativno 20/03/2026."
    out = build_spoken_text(text=t, output_lang="bs", max_chars=2000)
    s = out.spoken_text
    assert "kosa crta" not in s
    # For BHS we normalize into a natural, slash-free date form.
    assert "20 03 2026" in s


def test_spoken_text_normalizes_iso_date_bhs_2026_02_26() -> None:
    # Runtime bug report: ISO dates were being verbalized as structured tokens ("crta").
    t = "Rok je 2026-02-26."
    out = build_spoken_text(text=t, output_lang="bs", max_chars=2000)
    s = out.spoken_text
    assert "crta" not in s
    assert "2026-02-26" not in s
    assert "26 02 2026" in s
