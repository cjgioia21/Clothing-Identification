"""RN verification against the FTC registry data the user supplies."""

import pytest

from clothing_id.rn import (
    directory_from_env,
    load_directory,
    lookup_url,
    normalize_rn,
    verify,
)


@pytest.mark.parametrize(
    "raw,expected",
    [("RN# 051884", "51884"), ("rn 51884", "51884"), ("51884", "51884"), (None, ""), ("n/a", "")],
)
def test_rn_normalization(raw, expected):
    assert normalize_rn(raw) == expected


def test_lookup_url_points_at_the_ftc_database():
    assert lookup_url("RN 51884") == "https://rn.ftc.gov/rns?rn=51884"
    assert lookup_url(None) is None


def test_directory_loads_from_csv(tmp_path):
    path = tmp_path / "rn.csv"
    path.write_text("RN,Company\n51884,Patagonia Inc.\n00056,Levi Strauss & Co.\n")
    directory = load_directory(path)
    assert directory["51884"] == "Patagonia Inc."
    assert directory["56"] == "Levi Strauss & Co."


def test_directory_rejects_files_without_the_needed_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("foo,bar\n1,2\n")
    with pytest.raises(ValueError, match="needs an RN column"):
        load_directory(path)


def test_matching_registrant_confirms_the_brand():
    result = verify("RN 51884", "Patagonia", {"51884": "Patagonia, Inc."})
    assert result["registrant"] == "Patagonia, Inc."
    assert result["brand_matches_rn"] is True
    assert any("brand confirmed" in n for n in result["notes"])


def test_mismatched_registrant_is_called_out():
    result = verify("51884", "Supreme", {"51884": "Patagonia, Inc."})
    assert result["brand_matches_rn"] is False
    assert any("does not match" in n for n in result["notes"])


def test_unknown_rn_is_reported_as_unchecked_not_as_a_match():
    result = verify("12345", "Gap", {"51884": "Patagonia, Inc."})
    assert result["registrant"] is None
    assert result["brand_matches_rn"] is None
    assert result["lookup_url"].endswith("12345")


def test_no_directory_means_no_claim_either_way(monkeypatch):
    monkeypatch.delenv("CLOTHING_ID_RN_FILE", raising=False)
    result = verify("51884", "Patagonia")
    assert result["registrant"] is None
    assert result["brand_matches_rn"] is None
    assert any("no RN directory configured" in n for n in result["notes"])


def test_directory_from_env(tmp_path, monkeypatch):
    path = tmp_path / "rn.csv"
    path.write_text("rn,company\n51884,Patagonia Inc.\n")
    monkeypatch.setenv("CLOTHING_ID_RN_FILE", str(path))
    assert directory_from_env()["51884"] == "Patagonia Inc."
    monkeypatch.setenv("CLOTHING_ID_RN_FILE", str(tmp_path / "missing.csv"))
    assert directory_from_env() is None


def test_no_rn_on_the_tag_is_silent():
    result = verify(None, "Gap")
    assert result == {
        "rn_number": None,
        "registrant": None,
        "brand_matches_rn": None,
        "lookup_url": None,
        "notes": [],
    }
