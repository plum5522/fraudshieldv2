"""Race-condition test: many simultaneous reports, real Postgres only.

With check-then-insert, parallel requests can both see "not there" and both insert,
double-counting reporters. ON CONFLICT DO NOTHING + UNIQUE constraints must prevent that.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from app import reports
from app.extract import Entity
from app.trust import hash_reporter
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="needs a real Postgres (set TEST_DATABASE_URL)")

UPI = Entity("upi", "race.test@ybl")


def test_parallel_reports_count_each_person_once(session_factory):
    # 10 different people, each sending their report 5 times, all at once.
    jobs = [f"person-{i:02d}-device" for i in range(10)] * 5

    def send(reporter):
        with session_factory() as s:
            reports.record_report(s, [UPI], hash_reporter(reporter), "other")

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(send, jobs))

    with session_factory() as s:
        assert reports.reporter_counts(s, [UPI]) == {UPI.key: 10}
