from app.extract import Entity, clean_message, extract_entities, mask_entities


def keys(text):
    return [e.key for e in extract_entities(text)]


# Four real scam SMS received in October 2026 (scammer links only, no personal data).
REAL_1 = ("Airtel Warning: SPAM | Authority Notice: Your driving privileges may be restricted "
          "due to unpaid tickets. Visit https://echaIIan.com/gov to resolve and protect your "
          "mobility rights.")
REAL_2 = ("Airtel Warning: SPAM | AXIS Points: You have 3022 unused points, which will expire "
          "at 23:59 today (18th). After expiration, the points will be unusable. "
          "https://axirpek.icu/in")
REAL_3 = ("Overspeeding Notice: You violated speed limits, ticket issued. Pay the dues "
          "immediately to prevent additional charges & legal hassle. https://echallane.vip/in")
REAL_4 = ("India Post: Your parcel has arrived at the warehouse but cannot be delivered due to "
          "incomplete address information. Please use the link below to confirm your address "
          "within 12 hours.\n\nhttps://bit.ly/3WncZiR\n\n(Answer \"Y\" and click the link above, "
          "or copy the link and open in Safari)")


# ---------- Real messages ----------

def test_real_messages_entities():
    assert keys(REAL_1) == ["domain:echaiian.com"]
    assert keys(REAL_2) == ["domain:axirpek.icu"]
    assert keys(REAL_3) == ["domain:echallane.vip"]
    assert keys(REAL_4) == ["shortlink:bit.ly/3WncZiR"]  # path keeps its case


def test_carrier_tag_stripped():
    assert clean_message(REAL_1).startswith("Authority Notice:")
    assert clean_message(REAL_3) == REAL_3  # no tag, unchanged


def test_carrier_tag_variants():
    assert clean_message("Jio: Suspected Spam | Win Rs 5000 now") == "Win Rs 5000 now"
    assert clean_message("airtel warning: spam| hi") == "hi"


def test_spam_word_in_body_not_stripped():
    text = "Airtel: your bill is ready. Report spam to 1909"
    assert clean_message(text) == text


# ---------- UPI IDs ----------

def test_upi_basic():
    assert keys("Pay Rs 10 to refund.desk@ybl to get cashback") == ["upi:refund.desk@ybl"]


def test_upi_lowercased_and_trailing_period():
    assert keys("Send to KYC.Help@OKAXIS.") == ["upi:kyc.help@okaxis"]


def test_email_is_not_upi_or_domain():
    assert keys("Mail support@gmail.com for help") == []


# ---------- Phones ----------

def test_phone_formats_normalise_to_same_key():
    for raw in ["9876543210", "+91 98765 43210", "+91-98765-43210", "09876543210", "919876543210"]:
        assert keys(f"Call {raw} now") == ["phone:+919876543210"], raw


def test_phone_rejects_bad_numbers():
    assert keys("Ref 5876543210 and 12345678901") == []


def test_helpline_not_a_phone():
    assert keys("Report to 1930 or cybercrime.gov.in") == ["domain:cybercrime.gov.in"]


# ---------- Links ----------

def test_url_and_bare_domain():
    assert keys("Update at https://sbi-kyc-update.in/login?id=4 or visit lucky-draw.xyz/claim") == [
        "domain:sbi-kyc-update.in",
        "domain:lucky-draw.xyz",
    ]


def test_explicit_url_any_tld():
    assert keys("Go to https://pay-now.zzz/x") == ["domain:pay-now.zzz"]


def test_shortener_keyed_on_full_link():
    assert keys("see bit.ly/abc and bit.ly/XYZ") == ["shortlink:bit.ly/abc", "shortlink:bit.ly/XYZ"]


def test_amounts_are_not_domains():
    assert keys("You won Rs.500 cashback, i.e. instant credit") == []


# ---------- Masking ----------

def test_mask_real_message():
    assert mask_entities(clean_message(REAL_2)).endswith("will be unusable. <URL>")


def test_mask_keeps_sentence_punctuation():
    assert mask_entities("Visit https://x-pay.top/a. Then pay to pay@ybl or call 9876543210.") == (
        "Visit <URL>. Then pay to <UPI> or call <PHONE>."
    )


# ---------- Combined ----------

def test_mixed_message_dedup_and_order():
    msg = (
        "Dear customer your KYC is blocked. Pay 10 to verify@paytm or call "
        "+91 91234 56789. Link: http://kyc-verify.top/a . Again: verify@paytm"
    )
    assert keys(msg) == ["upi:verify@paytm", "phone:+919123456789", "domain:kyc-verify.top"]


def test_entity_key():
    assert Entity("upi", "a@ybl").key == "upi:a@ybl"
