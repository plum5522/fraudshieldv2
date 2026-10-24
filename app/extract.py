"""Deterministic entity extraction, cleaning and masking.

Three jobs, all pure functions (no database, no network), so they are trivial to test:

1. clean_message: strip labels a carrier added ("Airtel Warning: SPAM |"). Training on
   them would be data leakage: the model would learn the label, not the scam.
2. extract_entities: pull out the identifiers a scammer reuses (UPI IDs, phone numbers,
   links) and normalise them, so one scammer always maps to one key.
3. mask_entities: replace those identifiers with <UPI>, <PHONE>, <URL> before the text
   reaches the classifier. The model learns the scam's wording; the database learns
   the identities.

Why regex and not an LLM: one wrong character from a model would link two unrelated
scams. Regex is exact, fast, free and testable.
"""

import re
from dataclasses import dataclass

# ---------- 1. Carrier labels ----------

# e.g. "Airtel Warning: SPAM | ...", "Jio: Suspected Spam | ..."
_CARRIER_TAG = re.compile(
    r"^\s*(?:airtel|jio|vi|vodafone(?:\s+idea)?|bsnl)\b[^|\n]{0,40}\bspam\b[^|\n]{0,15}\|\s*",
    re.IGNORECASE,
)


def clean_message(text: str) -> str:
    return _CARRIER_TAG.sub("", text).strip()


# ---------- 2. Patterns ----------

# UPI ID (VPA): name@handle, where the handle is letters only (ybl, okaxis, paytm).
# The lookahead rejects emails: in "a@gmail.com" the handle is followed by ".com".
_UPI = re.compile(r"(?<![\w.-])([a-zA-Z0-9._-]{2,256})@([a-zA-Z]{2,64})(?![\w@]|\.[a-zA-Z])")

# Indian mobile: optional +91 / 91 / 0 prefix, then 10 digits starting 6-9.
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?|0)?([6-9]\d{4})[\s-]?(\d{5})(?!\d)")

# Links. Explicit http(s):// or www. links match with any TLD. Bare domains ("bit.ly/x")
# only match a known TLD, so "Rs.500" or "i.e." never count as links. Tradeoff: a bare
# domain on an unlisted TLD is missed.
_TLDS = (
    r"com|in|co|net|org|info|biz|xyz|top|online|site|app|me|io|ly|link|live|club|shop"
    r"|vip|icu|cc|ws|buzz|click|pro|tk|cn|ru|store|life|work|today"
)
_URL = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+"
    rf"|(?<![@\w.-])(?:[a-zA-Z0-9-]+\.)+(?:{_TLDS})(?:/[^\s<>\"']*)?(?![\w-])",
    re.IGNORECASE,
)

# Link shorteners hide the real site, so "bit.ly" itself says nothing. For these we
# key on the full short link (case-sensitive path), not the domain. Otherwise one report
# on bit.ly would flag every bit.ly link on the internet.
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "cutt.ly", "is.gd", "rb.gy",
              "shorturl.at", "tiny.cc", "ow.ly", "rebrand.ly"}

_TRAILING = ".,;:!?)]}'\""


@dataclass(frozen=True)
class Entity:
    kind: str   # "upi" | "phone" | "domain" | "shortlink"
    value: str  # normalised value

    @property
    def key(self) -> str:
        """Stable string key, e.g. 'upi:refund@ybl'."""
        return f"{self.kind}:{self.value}"


def _link_entity(raw: str) -> Entity | None:
    raw = raw.rstrip(_TRAILING)
    rest = re.sub(r"^(https?://)?(www\.)?", "", raw, flags=re.IGNORECASE)
    host, _, path = rest.partition("/")
    host = host.split("?")[0].split(":")[0].lower().rstrip(".")
    if not host:
        return None
    if host in SHORTENERS:
        code = re.split(r"[/?#]", path)[0]
        return Entity("shortlink", f"{host}/{code}") if code else None
    return Entity("domain", host)


def _find(text: str) -> list[tuple[int, int, Entity]]:
    """All matches as (start, end, entity), in text order."""
    hits: list[tuple[int, int, Entity]] = []
    for m in _UPI.finditer(text):
        hits.append((m.start(), m.end(), Entity("upi", f"{m.group(1)}@{m.group(2)}".lower())))
    for m in _PHONE.finditer(text):
        hits.append((m.start(), m.end(), Entity("phone", "+91" + m.group(1) + m.group(2))))
    for m in _URL.finditer(text):
        raw = m.group(0).rstrip(_TRAILING)  # keep a sentence's final "." out of the link
        ent = _link_entity(raw)
        if ent:
            hits.append((m.start(), m.start() + len(raw), ent))
    return sorted(hits, key=lambda h: h[0])


def extract_entities(text: str) -> list[Entity]:
    """Unique entities, in order of first appearance."""
    return list(dict.fromkeys(ent for _, _, ent in _find(text)))


_MASK = {"upi": "<UPI>", "phone": "<PHONE>", "domain": "<URL>", "shortlink": "<URL>"}


def mask_entities(text: str) -> str:
    """Replace every identifier with a placeholder, for the classifier."""
    out, pos = [], 0
    for start, end, ent in _find(text):
        if start < pos:  # overlapping match already masked
            continue
        out.append(text[pos:start])
        out.append(_MASK[ent.kind])
        pos = end
    out.append(text[pos:])
    return "".join(out)
