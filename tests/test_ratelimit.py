from concurrent.futures import ThreadPoolExecutor

from app.ratelimit import SlidingWindowLimiter


class FakeClock:
    """Lets tests move time forward instantly instead of sleeping."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_allows_up_to_limit_then_blocks():
    clock = FakeClock()
    rl = SlidingWindowLimiter(limit=3, window_seconds=60, clock=clock)
    assert [rl.check("a")[0] for _ in range(3)] == [True, True, True]
    allowed, retry = rl.check("a")
    assert not allowed and retry == 60


def test_window_slides():
    clock = FakeClock()
    rl = SlidingWindowLimiter(limit=2, window_seconds=60, clock=clock)
    rl.check("a")            # t=1000
    clock.t += 30
    rl.check("a")            # t=1030
    assert rl.check("a") == (False, 30)   # first slot frees at t=1060
    clock.t += 30            # t=1060: the t=1000 request has left the window
    assert rl.check("a")[0] is True
    assert rl.check("a")[0] is False      # t=1030 and t=1060 still inside


def test_no_boundary_burst():
    """The flaw of fixed windows: 2 at the end of one window + 2 at the start of the next."""
    clock = FakeClock()
    rl = SlidingWindowLimiter(limit=2, window_seconds=60, clock=clock)
    rl.check("a"); rl.check("a")          # noqa: E702
    clock.t += 1
    assert rl.check("a")[0] is False      # a fixed window starting here would allow it


def test_keys_are_independent():
    rl = SlidingWindowLimiter(limit=1, window_seconds=60, clock=FakeClock())
    assert rl.check("rohan")[0] and rl.check("meera")[0]
    assert rl.check("rohan")[0] is False


def test_refused_requests_are_not_recorded():
    clock = FakeClock()
    rl = SlidingWindowLimiter(limit=1, window_seconds=60, clock=clock)
    rl.check("a")
    for _ in range(50):      # hammering while blocked must not extend the block
        rl.check("a")
    clock.t += 60
    assert rl.check("a")[0] is True


def test_stale_keys_are_swept():
    clock = FakeClock()
    rl = SlidingWindowLimiter(limit=5, window_seconds=60, clock=clock)
    for i in range(999):
        rl.check(f"user-{i}")
    clock.t += 120
    rl.check("trigger")      # 1000th recorded call triggers a sweep
    assert rl.tracked_keys() == 1


def test_thread_safe_exact_limit():
    rl = SlidingWindowLimiter(limit=10, window_seconds=60)
    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(lambda _: rl.check("same-key")[0], range(200)))
    assert results.count(True) == 10
