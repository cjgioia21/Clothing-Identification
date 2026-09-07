from clothing_id.brands import TIERS, lookup_tier, normalize_brand


def test_normalize_strips_accents_punctuation_and_suffixes():
    assert normalize_brand("Comme des Garçons") == "comme des garcons"
    assert normalize_brand("Levi Strauss & Co.") == "levi strauss &"
    assert normalize_brand("  NIKE, Inc. ") == "nike"
    assert normalize_brand(None) == ""


def test_exact_and_alias_lookups():
    assert lookup_tier("Nike").name == "athletic"
    assert lookup_tier("The North Face").name == "outdoor"
    assert lookup_tier("Levi Strauss & Co.").name == "workwear"
    assert lookup_tier("Arc'teryx").name == "outdoor"


def test_sub_label_wins_over_house():
    assert lookup_tier("Ralph Lauren", "RRL").name == "designer"
    assert lookup_tier("Carhartt", "Carhartt WIP").name == "streetwear"


def test_unknown_brand_falls_back():
    tier = lookup_tier("Zephyr Goods of Ohio")
    assert tier.name == "unknown"
    assert tier.retail_multiplier == 1.0


def test_tiers_are_monotonic():
    order = ["fast_fashion", "mainstream", "contemporary", "designer", "luxury", "ultra_luxury"]
    multipliers = [TIERS[t].retail_multiplier for t in order]
    assert multipliers == sorted(multipliers)
