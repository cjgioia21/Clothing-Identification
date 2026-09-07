"""Brand tiers used to anchor retail price and resale recovery rates."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class Tier:
    name: str
    retail_multiplier: float  # vs. the mainstream baseline retail for a category
    resale_factor: float  # fraction of retail a used piece in excellent shape recovers
    collectible: bool = False  # whether vintage age adds a premium


TIERS: Dict[str, Tier] = {
    "fast_fashion": Tier("fast_fashion", 0.45, 0.08),
    "mainstream": Tier("mainstream", 1.00, 0.16),
    "athletic": Tier("athletic", 1.25, 0.22, collectible=True),
    "workwear": Tier("workwear", 1.40, 0.30, collectible=True),
    "outdoor": Tier("outdoor", 2.10, 0.38, collectible=True),
    "contemporary": Tier("contemporary", 2.20, 0.24),
    "premium": Tier("premium", 3.20, 0.30, collectible=True),
    "streetwear": Tier("streetwear", 2.40, 0.62, collectible=True),
    "designer": Tier("designer", 6.50, 0.40, collectible=True),
    "luxury": Tier("luxury", 12.00, 0.48, collectible=True),
    "ultra_luxury": Tier("ultra_luxury", 22.00, 0.55, collectible=True),
    "unknown": Tier("unknown", 1.00, 0.14),
}

# brand (normalized) -> tier key
BRAND_TIERS: Dict[str, str] = {
    # fast fashion / value
    "shein": "fast_fashion", "temu": "fast_fashion", "primark": "fast_fashion",
    "forever 21": "fast_fashion", "h&m": "fast_fashion", "divided": "fast_fashion",
    "zara": "fast_fashion", "boohoo": "fast_fashion", "romwe": "fast_fashion",
    "old navy": "fast_fashion", "george": "fast_fashion", "faded glory": "fast_fashion",
    "wal mart": "fast_fashion", "athletic works": "fast_fashion", "shein curve": "fast_fashion",
    "cato": "fast_fashion", "rue 21": "fast_fashion", "charlotte russe": "fast_fashion",
    "wild fable": "fast_fashion", "a new day": "fast_fashion", "goodfellow": "fast_fashion",
    "amazon essentials": "fast_fashion", "gildan": "fast_fashion", "hanes": "fast_fashion",
    "fruit of the loom": "fast_fashion", "port authority": "fast_fashion",
    "delta apparel": "fast_fashion", "jerzees": "fast_fashion", "bella canvas": "fast_fashion",
    # mainstream mall / department
    "gap": "mainstream", "banana republic": "mainstream", "j crew": "mainstream",
    "uniqlo": "mainstream", "american eagle": "mainstream", "aeropostale": "mainstream",
    "abercrombie fitch": "mainstream", "hollister": "mainstream", "express": "mainstream",
    "lands end": "mainstream", "l l bean": "mainstream", "eddie bauer": "mainstream",
    "talbots": "mainstream", "ann taylor": "mainstream", "loft": "mainstream",
    "chicos": "mainstream", "gymboree": "mainstream", "carters": "mainstream",
    "nautica": "mainstream", "izod": "mainstream", "chaps": "mainstream",
    "van heusen": "mainstream", "dockers": "mainstream", "haggar": "mainstream",
    "st johns bay": "mainstream", "croft barrow": "mainstream", "sonoma": "mainstream",
    "arizona jean": "mainstream", "mossimo": "mainstream", "merona": "mainstream",
    "lucky brand": "mainstream", "guess": "mainstream", "calvin klein": "mainstream",
    "tommy hilfiger": "mainstream", "nine west": "mainstream", "esprit": "mainstream",
    "benetton": "mainstream", "columbia": "mainstream", "quiksilver": "mainstream",
    "billabong": "mainstream", "roxy": "mainstream", "hurley": "mainstream",
    "volcom": "mainstream", "element": "mainstream", "dc shoes": "mainstream",
    "fox racing": "mainstream", "aerie": "mainstream", "pacsun": "mainstream",
    # athletic
    "nike": "athletic", "adidas": "athletic", "puma": "athletic", "reebok": "athletic",
    "under armour": "athletic", "new balance": "athletic", "asics": "athletic",
    "champion": "athletic", "starter": "athletic", "mitchell ness": "athletic",
    "russell athletic": "athletic", "fila": "athletic", "kappa": "athletic",
    "umbro": "athletic", "le coq sportif": "athletic", "saucony": "athletic",
    "brooks": "athletic", "hoka": "athletic", "on running": "athletic",
    "lululemon": "contemporary", "athleta": "mainstream", "gymshark": "mainstream",
    "vuori": "contemporary", "alo yoga": "contemporary", "tracksmith": "premium",
    "jordan": "athletic", "converse": "athletic", "vans": "athletic",
    "majestic": "athletic", "wilson": "athletic", "spalding": "athletic",
    # workwear / heritage
    "carhartt": "workwear", "carhartt wip": "streetwear", "dickies": "workwear",
    "wrangler": "workwear", "lee": "workwear", "levis": "workwear",
    "levis vintage clothing": "premium", "big smith": "workwear", "key imperial": "workwear",
    "ben davis": "workwear", "red kap": "workwear", "duluth trading": "workwear",
    "filson": "premium", "pointer brand": "workwear", "pendleton": "premium",
    "woolrich": "premium", "schott": "premium", "red wing": "premium",
    "thorogood": "workwear", "danner": "premium", "chippewa": "workwear",
    # outdoor / technical
    "patagonia": "outdoor", "the north face": "outdoor", "arcteryx": "outdoor",
    "mountain hardwear": "outdoor", "marmot": "outdoor", "rab": "outdoor",
    "mammut": "outdoor", "salomon": "outdoor", "black diamond": "outdoor",
    "outdoor research": "outdoor", "kuhl": "outdoor", "fjallraven": "outdoor",
    "canada goose": "luxury", "moncler": "luxury", "moose knuckles": "designer",
    "rei co op": "mainstream", "sierra designs": "outdoor", "gramicci": "outdoor",
    "helly hansen": "outdoor", "and wander": "designer", "snow peak": "premium",
    "veilance": "luxury", "norrona": "outdoor", "haglofs": "outdoor",
    # streetwear / hype
    "supreme": "streetwear", "bape": "streetwear", "a bathing ape": "streetwear",
    "stussy": "streetwear", "palace": "streetwear", "kith": "streetwear",
    "off white": "designer", "fear of god": "designer", "essentials": "streetwear",
    "yeezy": "streetwear", "anti social social club": "streetwear",
    "corteiz": "streetwear", "aime leon dore": "streetwear", "noah": "streetwear",
    "brain dead": "streetwear", "human made": "designer", "cactus plant flea market": "streetwear",
    "gallery dept": "designer", "chrome hearts": "ultra_luxury", "vetements": "designer",
    "hellstar": "streetwear", "sp5der": "streetwear", "denim tears": "streetwear",
    "stone island": "designer", "cp company": "premium", "represent": "contemporary",
    # contemporary / premium
    "everlane": "contemporary", "cos": "contemporary", "arket": "contemporary",
    "reiss": "contemporary", "ted baker": "contemporary", "allsaints": "contemporary",
    "rag bone": "premium", "theory": "premium", "vince": "premium",
    "club monaco": "contemporary", "madewell": "contemporary", "aritzia": "contemporary",
    "sandro": "premium", "maje": "premium", "the kooples": "premium",
    "apc": "premium", "buck mason": "contemporary", "todd snyder": "premium",
    "j press": "premium", "brooks brothers": "premium", "ralph lauren": "premium",
    "polo ralph lauren": "premium", "rlx": "premium", "rrl": "designer",
    "purple label": "luxury", "lacoste": "contemporary", "fred perry": "contemporary",
    "barbour": "premium", "mackintosh": "designer", "aquascutum": "premium",
    "burberry": "luxury", "paul smith": "premium", "ted lapidus": "contemporary",
    "hugo boss": "premium", "armani exchange": "contemporary", "diesel": "contemporary",
    "g star raw": "contemporary", "true religion": "contemporary", "evisu": "premium",
    "iron heart": "premium", "3sixteen": "premium", "naked famous": "premium",
    "orslow": "premium", "beams": "premium", "engineered garments": "designer",
    "visvim": "ultra_luxury", "kapital": "designer", "needles": "designer",
    "universal works": "premium", "nigel cabourn": "designer", "our legacy": "designer",
    # designer
    "acne studios": "designer", "ami paris": "designer", "jacquemus": "designer",
    "isabel marant": "designer", "ganni": "contemporary", "toteme": "designer",
    "khaite": "luxury", "the row": "ultra_luxury", "lemaire": "designer",
    "dries van noten": "designer", "comme des garcons": "designer",
    "yohji yamamoto": "designer", "issey miyake": "designer", "junya watanabe": "designer",
    "maison margiela": "luxury", "rick owens": "luxury", "raf simons": "luxury",
    "helmut lang": "designer", "jil sander": "luxury", "marni": "luxury",
    "thom browne": "luxury", "alexander wang": "designer", "self portrait": "designer",
    "reformation": "contemporary", "staud": "contemporary", "zimmermann": "luxury",
    "diane von furstenberg": "designer", "coach": "designer", "michael kors": "contemporary",
    "kate spade": "contemporary", "marc jacobs": "designer", "tory burch": "designer",
    "sandy liang": "designer", "nanushka": "designer", "wales bonner": "luxury",
    "bode": "luxury", "casablanca": "luxury", "amiri": "luxury",
    # luxury / ultra luxury
    "gucci": "luxury", "prada": "luxury", "miu miu": "luxury", "fendi": "luxury",
    "versace": "luxury", "valentino": "luxury", "givenchy": "luxury",
    "balenciaga": "luxury", "saint laurent": "luxury", "yves saint laurent": "luxury",
    "celine": "ultra_luxury", "dior": "ultra_luxury", "christian dior": "ultra_luxury",
    "chanel": "ultra_luxury", "louis vuitton": "ultra_luxury", "hermes": "ultra_luxury",
    "bottega veneta": "ultra_luxury", "loro piana": "ultra_luxury", "brunello cucinelli": "ultra_luxury",
    "zegna": "luxury", "ermenegildo zegna": "luxury", "kiton": "ultra_luxury",
    "brioni": "ultra_luxury", "tom ford": "ultra_luxury", "loewe": "ultra_luxury",
    "alexander mcqueen": "luxury", "balmain": "luxury", "off white co": "designer",
    "canali": "luxury", "corneliani": "luxury", "santoni": "luxury",
    "church s": "luxury", "john lobb": "ultra_luxury", "edward green": "ultra_luxury",
    "alden": "luxury", "crockett jones": "luxury", "allen edmonds": "premium",
}

# Alternate spellings that appear on tags, mapped onto the canonical keys above.
ALIASES: Dict[str, str] = {
    "levi strauss": "levis",
    "levi": "levis",
    "lvc": "levis vintage clothing",
    "tnf": "the north face",
    "north face": "the north face",
    "arc teryx": "arcteryx",
    "cdg": "comme des garcons",
    "play comme des garcons": "comme des garcons",
    "ysl": "saint laurent",
    "lv": "louis vuitton",
    "a p c": "apc",
    "rl": "ralph lauren",
    "polo by ralph lauren": "polo ralph lauren",
    "polo sport": "polo ralph lauren",
    "chaps ralph lauren": "chaps",
    "double rl": "rrl",
    "nike sportswear": "nike",
    "nike acg": "nike",
    "air jordan": "jordan",
    "adidas originals": "adidas",
    "harley davidson": "workwear",
    "ape": "a bathing ape",
    "assc": "anti social social club",
    "fog": "fear of god",
    "fear of god essentials": "essentials",
    "the north face purple label": "designer",
    "uniqlo u": "uniqlo",
    "gap denim": "gap",
    "old navy active": "old navy",
    "j crew factory": "j crew",
    "banana republic factory": "banana republic",
    "eddie bauer expedition outfitter": "eddie bauer",
    "l l bean freeport maine": "l l bean",
    "champion reverse weave": "champion",
    "hanes beefy t": "hanes",
    "carhartt work in progress": "carhartt wip",
    "dickies 874": "dickies",
    "stussy international": "stussy",
    "supreme new york": "supreme",
    "ck": "calvin klein",
    "ck calvin klein": "calvin klein",
    "tommy jeans": "tommy hilfiger",
    "tommy": "tommy hilfiger",
    "hilfiger": "tommy hilfiger",
    "gh bass": "mainstream",
    "izod lacoste": "lacoste",
    "lacoste sport": "lacoste",
    "boss": "hugo boss",
    "hugo": "hugo boss",
    "emporio armani": "premium",
    "giorgio armani": "luxury",
    "armani collezioni": "luxury",
    "dolce gabbana": "luxury",
    "d&g": "luxury",
    "d & g": "luxury",
    "salvatore ferragamo": "luxury",
    "ferragamo": "luxury",
    "max mara": "luxury",
    "sportmax": "designer",
    "acne": "acne studios",
    "margiela": "maison margiela",
    "mm6": "designer",
    "mm6 maison margiela": "designer",
    "y 3": "designer",
    "y3": "designer",
    "adidas y 3": "designer",
    "the north face summit series": "the north face",
    "columbia sportswear": "columbia",
    "eb": "eddie bauer",
}

# Distinctive words that imply a tier when the exact brand is unknown.
KEYWORD_TIERS = (
    ("vintage tag", None),
    ("hand made in italy", "luxury"),
    ("made in italy", "premium"),
    ("union made", "workwear"),
    ("gore tex", "outdoor"),
)


def normalize_brand(name: Optional[str]) -> str:
    """Lowercase, strip accents, drop punctuation and legal/filler words."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[\u00ae\u2122\u00a9]", " ", text)
    text = re.sub(r"[^a-z0-9&]+", " ", text)
    text = re.sub(
        r"\b(inc|llc|ltd|co|company|corp|gmbh|s p a|spa|sas|srl|the|brand|apparel|clothing)\b",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


# Keys are normalized once so lookups compare like with like.
_BRANDS: Dict[str, str] = {normalize_brand(k): v for k, v in BRAND_TIERS.items()}
_ALIASES: Dict[str, str] = {normalize_brand(k): v for k, v in ALIASES.items()}


def _resolve(key: str) -> Optional[str]:
    """Return a tier key for a normalized brand string, or None."""
    if not key:
        return None
    if key in _BRANDS:
        return _BRANDS[key]
    target = _ALIASES.get(key)
    if target is not None:
        if target in TIERS:
            return target
        resolved = _BRANDS.get(normalize_brand(target))
        if resolved:
            return resolved
    words = key.split()
    for known, tier_key in _BRANDS.items():
        if len(known) >= 4 and (key.startswith(known + " ") or known in (" ".join(words),)):
            return tier_key
    for known, tier_key in _BRANDS.items():
        if len(known) >= 6 and known in key:
            return tier_key
    for known, tier_key in _ALIASES.items():
        if len(known) >= 6 and known in key:
            return tier_key if tier_key in TIERS else _BRANDS.get(normalize_brand(tier_key))
    return None


def lookup_tier(brand: Optional[str], sub_label: Optional[str] = None) -> Tier:
    """Resolve a printed brand name (or sub-label) to a pricing tier.

    Sub-labels are tried first because they are more specific than the parent
    house (RRL under Ralph Lauren, Carhartt WIP under Carhartt).
    """
    for candidate in (sub_label, brand):
        tier_key = _resolve(normalize_brand(candidate))
        if tier_key:
            return TIERS[tier_key]
    return TIERS["unknown"]


def is_known_brand(brand: Optional[str], sub_label: Optional[str] = None) -> bool:
    return lookup_tier(brand, sub_label).name != "unknown"
