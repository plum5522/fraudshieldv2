"""Repository tests: the database rules, without HTTP."""

from datetime import timedelta

from app import reports
from app.extract import Entity
from app.trust import hash_reporter

UPI = Entity("upi", "refund.desk@ybl")
PHONE = Entity("phone", "+919876543210")
NOW = reports.utcnow()


def test_new_reports_are_counted(session):
    for person in ["rohan-device", "meera-device", "kabir-device"]:
        reports.record_report(session, [UPI], hash_reporter(person), "kyc_freeze", NOW)
    assert reports.reporter_counts(session, [UPI], NOW) == {UPI.key: 3}


def test_same_person_counts_once(session):
    h = hash_reporter("rohan-device")
    first = reports.record_report(session, [UPI], h, "kyc_freeze", NOW)
    again = reports.record_report(session, [UPI], h, "kyc_freeze", NOW)
    assert first == {UPI.key: True}
    assert again == {UPI.key: False}
    assert reports.reporter_counts(session, [UPI], NOW) == {UPI.key: 1}


def test_unreported_entity_counts_zero(session):
    assert reports.reporter_counts(session, [PHONE], NOW) == {PHONE.key: 0}


def test_old_reports_fall_out_of_window(session):
    reports.record_report(session, [UPI], hash_reporter("a-device"), "other", NOW - timedelta(days=45))
    reports.record_report(session, [UPI], hash_reporter("b-device"), "other", NOW - timedelta(days=2))
    assert reports.reporter_counts(session, [UPI], NOW) == {UPI.key: 1}


def test_counts_for_several_entities_in_one_call(session):
    reports.record_report(session, [UPI, PHONE], hash_reporter("a-device"), "other", NOW)
    reports.record_report(session, [UPI], hash_reporter("b-device"), "other", NOW)
    assert reports.reporter_counts(session, [UPI, PHONE], NOW) == {UPI.key: 2, PHONE.key: 1}


def test_history(session):
    reports.record_report(session, [UPI], hash_reporter("a-device"), "kyc_freeze", NOW - timedelta(days=40))
    reports.record_report(session, [UPI], hash_reporter("b-device"), "kyc_freeze", NOW)
    reports.record_report(session, [UPI], hash_reporter("c-device"), "lottery", NOW)
    h = reports.entity_history(session, UPI, NOW)
    assert h["reporters_total"] == 3
    assert h["reporters_recent"] == 2
    assert h["categories"] == {"kyc_freeze": 2, "lottery": 1}
    assert h["first_seen"] < h["last_seen"]


def test_history_unknown_entity(session):
    assert reports.entity_history(session, PHONE, NOW) is None


def test_reporter_hash_is_stable_and_not_raw():
    assert hash_reporter("rohan-device") == hash_reporter("rohan-device")
    assert hash_reporter("rohan-device") != hash_reporter("meera-device")
    assert "rohan" not in hash_reporter("rohan-device")
    assert len(hash_reporter("x" * 8)) == 64
