"""Identifiers that must never count as scam evidence, and reporter hashing."""

import hashlib
import hmac

from app.config import settings
from app.extract import Entity

# Official and huge platforms. Scam messages often mention them ("report to
# cybercrime.gov.in"); if they could collect reports, they'd get flagged.
# Subdomains are covered too (echallan.parivahan.gov.in).
TRUSTED_DOMAINS = {
    "gov.in", "nic.in", "npci.org.in", "rbi.org.in", "sbi.co.in", "onlinesbi.sbi",
    "hdfcbank.com", "icicibank.com", "axisbank.com", "indiapost.gov.in",
    "google.com", "whatsapp.com", "amazon.in", "flipkart.com", "paytm.com", "phonepe.com",
}


def is_trusted(entity: Entity) -> bool:
    if entity.kind != "domain":
        return False
    return any(entity.value == d or entity.value.endswith("." + d) for d in TRUSTED_DOMAINS)


def hash_reporter(reporter_id: str) -> str:
    """HMAC-SHA256 with a server secret. A plain SHA-256 of a device ID can be reversed
    by brute force (device IDs are guessable); without the secret, an HMAC cannot."""
    return hmac.new(settings.reporter_secret.encode(), reporter_id.encode(), hashlib.sha256).hexdigest()
