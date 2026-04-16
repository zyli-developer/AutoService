from __future__ import annotations

import pytest
import pytest_asyncio  # noqa: F401 – ensures plugin is loaded

from autoservice.low_peak_scheduler import LowPeakScheduler


# ---------------------------------------------------------------------------
# 1. Import and instantiate
# ---------------------------------------------------------------------------

def test_import_and_instantiate():
    scheduler = LowPeakScheduler()
    assert scheduler.threshold == 0.2
    assert scheduler.window_minutes == 30
    assert scheduler.min_samples == 3


# ---------------------------------------------------------------------------
# 2. record_sample stores data
# ---------------------------------------------------------------------------

def test_record_sample_stores_data():
    s = LowPeakScheduler()
    s.record_sample(100.0, timestamp=1000.0)
    assert len(s._samples) == 1
    assert s._samples[0] == (1000.0, 100.0)


# ---------------------------------------------------------------------------
# 3. current_avg computes 30-min window average
# ---------------------------------------------------------------------------

def test_current_avg_window_average():
    s = LowPeakScheduler()
    base = 1000.0
    s.record_sample(10.0, timestamp=base)
    s.record_sample(20.0, timestamp=base + 60)
    s.record_sample(30.0, timestamp=base + 120)
    assert s.current_avg() == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# 4. Old samples auto-pruned from average
# ---------------------------------------------------------------------------

def test_old_samples_pruned():
    s = LowPeakScheduler(window_minutes=30)
    base = 1000.0
    # Sample outside the window (31 minutes ago relative to latest)
    s.record_sample(100.0, timestamp=base)
    # Samples inside the window
    s.record_sample(10.0, timestamp=base + 31 * 60)
    s.record_sample(20.0, timestamp=base + 32 * 60)
    # The old 100.0 sample should be pruned
    assert s.current_avg() == pytest.approx(15.0)


# ---------------------------------------------------------------------------
# 5. peak_qps tracks 24h max
# ---------------------------------------------------------------------------

def test_peak_qps_tracks_24h_max():
    s = LowPeakScheduler()
    base = 1000.0
    s.record_sample(50.0, timestamp=base)
    s.record_sample(200.0, timestamp=base + 60)
    s.record_sample(30.0, timestamp=base + 120)
    # Peak should reflect the highest window-average recorded
    assert s.peak_qps >= 50.0  # at minimum the first sample's avg


# ---------------------------------------------------------------------------
# 6. is_low_peak True when avg < 20% of peak
# ---------------------------------------------------------------------------

def test_is_low_peak_true_below_threshold():
    s = LowPeakScheduler(threshold=0.2, min_samples=3)
    base = 1000.0
    # Build up a high peak
    s.record_sample(100.0, timestamp=base)
    s.record_sample(100.0, timestamp=base + 60)
    s.record_sample(100.0, timestamp=base + 120)
    # Now move forward (still within 24h) and record low traffic
    # Need to push old samples out of the 30-min window
    low_base = base + 31 * 60
    s.record_sample(5.0, timestamp=low_base)
    s.record_sample(5.0, timestamp=low_base + 60)
    s.record_sample(5.0, timestamp=low_base + 120)
    # avg = 5.0, peak >= 100.0, 5 < 0.2 * 100 = 20 → True
    assert s.is_low_peak() is True


# ---------------------------------------------------------------------------
# 7. is_low_peak False when avg >= 20% of peak
# ---------------------------------------------------------------------------

def test_is_low_peak_false_above_threshold():
    s = LowPeakScheduler(threshold=0.2, min_samples=3)
    base = 1000.0
    s.record_sample(100.0, timestamp=base)
    s.record_sample(100.0, timestamp=base + 60)
    s.record_sample(100.0, timestamp=base + 120)
    # avg = 100, peak = 100, 100 >= 0.2 * 100 → False
    assert s.is_low_peak() is False


# ---------------------------------------------------------------------------
# 8. is_low_peak True at zero traffic
# ---------------------------------------------------------------------------

def test_is_low_peak_zero_traffic():
    s = LowPeakScheduler(min_samples=3)
    base = 1000.0
    # Build peak first
    s.record_sample(100.0, timestamp=base)
    s.record_sample(100.0, timestamp=base + 60)
    s.record_sample(100.0, timestamp=base + 120)
    # Move to new window with zero traffic
    zero_base = base + 31 * 60
    s.record_sample(0.0, timestamp=zero_base)
    s.record_sample(0.0, timestamp=zero_base + 60)
    s.record_sample(0.0, timestamp=zero_base + 120)
    assert s.is_low_peak() is True


# ---------------------------------------------------------------------------
# 9. Cold start protection (not enough samples -> False)
# ---------------------------------------------------------------------------

def test_cold_start_protection():
    s = LowPeakScheduler(min_samples=3)
    s.record_sample(1.0, timestamp=1000.0)
    s.record_sample(1.0, timestamp=1060.0)
    # Only 2 samples, min_samples=3
    assert s.is_low_peak() is False


# ---------------------------------------------------------------------------
# 10. on_low_peak callback registration + trigger
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_on_low_peak_callback_trigger():
    s = LowPeakScheduler(threshold=0.2, min_samples=3)
    triggered = []

    async def cb():
        triggered.append(True)

    s.on_low_peak(cb)

    base = 1000.0
    # Build peak
    s.record_sample(100.0, timestamp=base)
    s.record_sample(100.0, timestamp=base + 60)
    s.record_sample(100.0, timestamp=base + 120)
    # Drop to low
    low_base = base + 31 * 60
    s.record_sample(1.0, timestamp=low_base)
    s.record_sample(1.0, timestamp=low_base + 60)
    s.record_sample(1.0, timestamp=low_base + 120)

    await s.check_and_trigger()
    assert len(triggered) == 1


# ---------------------------------------------------------------------------
# 11. Callback dedup (only fires once per low-peak period)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_callback_dedup():
    s = LowPeakScheduler(threshold=0.2, min_samples=3)
    triggered = []

    async def cb():
        triggered.append(True)

    s.on_low_peak(cb)

    base = 1000.0
    s.record_sample(100.0, timestamp=base)
    s.record_sample(100.0, timestamp=base + 60)
    s.record_sample(100.0, timestamp=base + 120)

    low_base = base + 31 * 60
    s.record_sample(1.0, timestamp=low_base)
    s.record_sample(1.0, timestamp=low_base + 60)
    s.record_sample(1.0, timestamp=low_base + 120)

    await s.check_and_trigger()
    await s.check_and_trigger()
    await s.check_and_trigger()
    # Should only fire once despite multiple checks
    assert len(triggered) == 1


# ---------------------------------------------------------------------------
# 12. Recovery resets trigger flag
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recovery_resets_trigger():
    s = LowPeakScheduler(threshold=0.2, min_samples=3)
    triggered = []

    async def cb():
        triggered.append(True)

    s.on_low_peak(cb)

    base = 1000.0
    # Build peak
    s.record_sample(100.0, timestamp=base)
    s.record_sample(100.0, timestamp=base + 60)
    s.record_sample(100.0, timestamp=base + 120)

    # Drop to low -> trigger
    low_base = base + 31 * 60
    s.record_sample(1.0, timestamp=low_base)
    s.record_sample(1.0, timestamp=low_base + 60)
    s.record_sample(1.0, timestamp=low_base + 120)
    await s.check_and_trigger()
    assert len(triggered) == 1

    # Recover traffic -> reset
    recover_base = low_base + 31 * 60
    s.record_sample(100.0, timestamp=recover_base)
    s.record_sample(100.0, timestamp=recover_base + 60)
    s.record_sample(100.0, timestamp=recover_base + 120)
    await s.check_and_trigger()  # not low peak, resets _triggered

    # Drop again -> should fire again
    low2_base = recover_base + 31 * 60
    s.record_sample(1.0, timestamp=low2_base)
    s.record_sample(1.0, timestamp=low2_base + 60)
    s.record_sample(1.0, timestamp=low2_base + 120)
    await s.check_and_trigger()
    assert len(triggered) == 2


# ---------------------------------------------------------------------------
# 13. Custom threshold (0.3)
# ---------------------------------------------------------------------------

def test_custom_threshold():
    s = LowPeakScheduler(threshold=0.3, min_samples=3)
    base = 1000.0
    s.record_sample(100.0, timestamp=base)
    s.record_sample(100.0, timestamp=base + 60)
    s.record_sample(100.0, timestamp=base + 120)

    low_base = base + 31 * 60
    # 25 is below 0.3 * 100 = 30
    s.record_sample(25.0, timestamp=low_base)
    s.record_sample(25.0, timestamp=low_base + 60)
    s.record_sample(25.0, timestamp=low_base + 120)
    assert s.is_low_peak() is True

    # But 25 would NOT be low peak at threshold=0.2 (25 >= 20)
    s2 = LowPeakScheduler(threshold=0.2, min_samples=3)
    s2.record_sample(100.0, timestamp=base)
    s2.record_sample(100.0, timestamp=base + 60)
    s2.record_sample(100.0, timestamp=base + 120)
    s2.record_sample(25.0, timestamp=low_base)
    s2.record_sample(25.0, timestamp=low_base + 60)
    s2.record_sample(25.0, timestamp=low_base + 120)
    assert s2.is_low_peak() is False


# ---------------------------------------------------------------------------
# 14. Custom window_minutes (15)
# ---------------------------------------------------------------------------

def test_custom_window_minutes():
    s = LowPeakScheduler(window_minutes=15, min_samples=3)
    base = 1000.0
    s.record_sample(100.0, timestamp=base)
    s.record_sample(100.0, timestamp=base + 60)
    s.record_sample(100.0, timestamp=base + 120)

    # 16 minutes later, old samples should be pruned with 15-min window
    later = base + 16 * 60
    s.record_sample(5.0, timestamp=later)
    s.record_sample(5.0, timestamp=later + 60)
    s.record_sample(5.0, timestamp=later + 120)
    assert s.current_avg() == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# 15. record_from_metrics convenience method
# ---------------------------------------------------------------------------

def test_record_from_metrics():
    s = LowPeakScheduler()

    class FakeMetrics:
        messages_sent = 42

    s.record_from_metrics(FakeMetrics())
    assert len(s._samples) == 1
    assert s._samples[0][1] == 42.0
