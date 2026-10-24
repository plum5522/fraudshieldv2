from app.extract import Entity, extract_entities


def keys(text):
    return [e.key for e in extract_entities(text)]


# ---------- UPI IDs ----------

def test_upi_basic():
    assert keys("Pay Rs 10 to refund.desk@ybl to get cashback") == ["upi:refund.desk@ybl"]


def test_upi_lowercased_and_trailing_period():
    assert keys("Send to KYC.Help@OKAXIS.") == ["upi:kyc.help@okaxis"]


def test_email_is_not_upi():
    assert "upi:support@gmail" not in keys("Mail support@gmail.com for help")


# ---------- Phones ----------

def test_phone_formats_normalise_to_same_key():
    for raw in ["9876543210", "+91 98765 43210", "+91-98765-43210", "09876543210", "919876543210"]:
        assert keys(f"Call {raw} now") == ["phone:+919876543210"], raw


def test_phone_rejects_bad_numbers():
    # starts with 5, and an 11-digit run that is not a valid prefix form
    assert keys("Ref 5876543210 and 12345678901") == []


def test_helpline_not_a_phone():
    assert keys("Report to 1930 or cybercrime.gov.in") == ["domain:cybercrime.gov.in"]


# ---------- Domains ----------

def test_url_and_bare_domain():
    assert keys("Update at https://sbi-kyc-update.in/login?id=4 or visit bit.ly/x9z") == [
        "domain:sbi-kyc-update.in",
        "domain:bit.ly",
    ]


def test_www_prefix_stripped():
    assert keys("Go to www.Lucky-Draw.xyz now") == ["domain:lucky-draw.xyz"]


def test_amounts_are_not_domains():
    assert keys("You won Rs.500 cashback, i.e. instant credit") == []


def test_email_domain_not_extracted():
    assert keys("Write to help@gmail.com") == []


# ---------- Combined ----------

def test_mixed_message_dedup_and_order():
    msg = (
        "Dear customer your KYC is blocked. Pay 10 to verify@paytm or call "
        "+91 91234 56789. Link: http://kyc-verify.top/a . Again: verify@paytm"
    )
    assert keys(msg) == [
        "upi:verify@paytm",
        "phone:+919123456789",
        "domain:kyc-verify.top",
    ]


def test_entity_key():
    assert Entity("upi", "a@ybl").key == "upi:a@ybl"
