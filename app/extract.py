"""Deterministic entity extraction.

Pulls the identifiers a scammer reuses (UPI IDs, phone numbers, web domains)
out of a message and normalises them, so the same scammer always maps to the
same key no matter how the message formats it.

Why regex and not the LLM: an LLM can misspell or invent an ID, and one wrong
character would link two unrelated scams. Regex is exact, fast, free, and
testable.
"""

import re
from dataclasses import dataclass

# UPI ID (VPA): name@handle, where the handle is letters only (ybl, okaxis, paytm).
# The lookahead rejects emails: in "a@gmail.com" the handle is followed by ".com".
_UPI = re.compile(r"(?<![\w.-])([a-zA-Z0-9._-]{2,256})@([a-zA-Z]{2,64})(?![\w@]|\.[a-zA-Z])")

# Indian mobile: optional +91 / 91 / 0 prefix, then 10 digits starting 6-9.
# Spaces or hyphens are allowed inside ("98765 43210", "+91-98765-43210").
_PHONE = re.compile(r"(?<!\d)(?:\+?91[\s-]?|0)?([6-9]\d{4})[\s-]?(\d{5})(?!\d)")

# Links: explicit URLs, or bare domains with a common TLD ("bit.ly/x", "sbi-kyc.in").
# The TLD list keeps "Rs.500" or "e.g" from matching. The lookbehind skips email domains.
_TLDS = r"com|in|co|net|org|info|xyz|top|online|site|app|me|io|ly|link|live|club|shop"
_URL = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+"
    rf"|(?<![@\w.-])(?:[a-zA-Z0-9-]+\.)+(?:{_TLDS})(?:/[^\s<>\"']*)?(?![\w-])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Entity:
    kind: str   # "upi" | "phone" | "domain"
    value: str  # normalised value

    @property
    def key(self) -> str:
        """Stable string key, e.g. 'upi:refund@ybl'. Used as the graph node id."""
        return f"{self.kind}:{self.value}"


def _domain_of(url: str) -> str:
    url = re.sub(r"^(https?://)?(www\.)?", "", url, flags=re.IGNORECASE)
    host = url.split("/")[0].split("?")[0].split(":")[0]
    return host.lower().rstrip(".,;:!)")


def extract_entities(text: str) -> list[Entity]:
    """Return unique entities in order of first appearance."""
    found: list[Entity] = []

    for m in _UPI.finditer(text):
        found.append(Entity("upi", f"{m.group(1)}@{m.group(2)}".lower()))

    for m in _PHONE.finditer(text):
        found.append(Entity("phone", "+91" + m.group(1) + m.group(2)))

    for m in _URL.finditer(text):
        domain = _domain_of(m.group(0))
        if domain:
            found.append(Entity("domain", domain))

    # dict.fromkeys keeps order and drops duplicates
    return list(dict.fromkeys(found))
