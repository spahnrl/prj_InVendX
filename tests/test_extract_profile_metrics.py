"""extract_profile_metrics — AUM / advisor / RIA / accounts hints from marketing copy."""

from invendx.extract.patterns import extract_profile_metrics


def test_aum_trillions_suffix_unchanged() -> None:
    m = extract_profile_metrics("We manage $6T in client assets.")
    assert m.get("aum_trillions_hint") == "$6T"


def test_aum_trillion_word() -> None:
    m = extract_profile_metrics("More than $2.5 trillion in assets.")
    assert m.get("aum_trillions_hint") == "$2.5 trillion"


def test_aum_billions() -> None:
    m = extract_profile_metrics("Platform supports $50B in AUM.")
    assert m.get("aum_trillions_hint") == "$50B"


def test_aum_billion_word() -> None:
    m = extract_profile_metrics("Over $32 billion assets under management.")
    assert m.get("aum_trillions_hint") == "$32 billion"


def test_advisors_tilde_prefix_unchanged() -> None:
    m = extract_profile_metrics("Trusted by ~ 5,000+ RIAs worldwide.")
    assert "5,000" in (m.get("advisors_or_institutions_hint") or "")
    assert m.get("ria_hint") == 5000


def test_advisors_without_tilde() -> None:
    m = extract_profile_metrics("More than 1,200 advisors rely on our platform.")
    assert "1,200" in (m.get("advisors_or_institutions_hint") or "")


def test_rias_plus_suffix() -> None:
    m = extract_profile_metrics("Join 3,500+ RIAs on the network.")
    assert m.get("ria_hint") == 3500


def test_ria_registered_phrase() -> None:
    m = extract_profile_metrics("Serving over 900 registered investment advisers.")
    assert m.get("ria_hint") == 900


def test_ria_max_in_blob() -> None:
    m = extract_profile_metrics("100 RIAs in 2010. Now 5,000+ RIAs use us.")
    assert m.get("ria_hint") == 5000


def test_accounts_millions_unchanged() -> None:
    m = extract_profile_metrics("Across 2.5 million accounts globally.")
    assert m.get("accounts_millions_hint")


def test_empty_text() -> None:
    assert extract_profile_metrics("") == {}
    assert extract_profile_metrics("   ") == {}


def test_rias_tight_plus_no_space() -> None:
    m = extract_profile_metrics("Join 5,000+RIAs who trust us.")
    assert m.get("ria_hint") == 5000


def test_ria_firms_phrase() -> None:
    m = extract_profile_metrics("We partner with 900 RIA firms across the US.")
    assert m.get("ria_hint") == 900


def test_ria_colon_count() -> None:
    m = extract_profile_metrics("RIAs: 8,000 use our platform.")
    assert m.get("ria_hint") == 8000


def test_rias_10k_suffix() -> None:
    m = extract_profile_metrics("More than 10K+ RIAs on our network.")
    assert m.get("ria_hint") == 10_000


def test_independent_rias() -> None:
    m = extract_profile_metrics("Built for 1,200 independent RIAs.")
    assert m.get("ria_hint") == 1200
