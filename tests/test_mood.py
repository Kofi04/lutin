"""The CPU/RAM/battery to mood mapping, and the CPU sampler's delta maths."""

from __future__ import annotations

from wizard.config import MonitorSettings
from wizard.features.monitor import Sample, mood_for
from wizard.mood import Mood, claude_mood_for, combine
from wizard.winapi import CpuSampler

SETTINGS = MonitorSettings(
    cpu_busy=65.0, cpu_stressed=88.0, ram_stressed=88.0, battery_low=20
)


def sample(cpu=5.0, ram=40.0, battery=None, on_ac=True) -> Sample:
    return Sample(cpu=cpu, ram=ram, battery_percent=battery, on_ac=on_ac)


def test_idle_machine_is_calm():
    assert mood_for(sample(), SETTINGS) is Mood.CALM


def test_busy_threshold():
    assert mood_for(sample(cpu=64.9), SETTINGS) is Mood.CALM
    assert mood_for(sample(cpu=65.0), SETTINGS) is Mood.BUSY


def test_high_cpu_or_high_ram_is_stressed():
    assert mood_for(sample(cpu=95.0), SETTINGS) is Mood.STRESSED
    assert mood_for(sample(ram=92.0), SETTINGS) is Mood.STRESSED


def test_low_battery_on_battery_power_is_tired():
    assert mood_for(sample(battery=15, on_ac=False), SETTINGS) is Mood.TIRED


def test_low_battery_while_charging_is_not_tired():
    assert mood_for(sample(battery=15, on_ac=True), SETTINGS) is Mood.CALM


def test_desktop_without_a_battery_is_never_tired():
    assert mood_for(sample(battery=None, on_ac=False), SETTINGS) is Mood.CALM


def test_stress_wins_over_tiredness():
    # Both conditions hold; the actionable one should show.
    busy_and_flat = sample(cpu=99.0, battery=5, on_ac=False)
    assert mood_for(busy_and_flat, SETTINGS) is Mood.STRESSED


def test_summary_mentions_battery_only_when_present():
    # The summary is user-facing French, with a non-breaking space before "%".
    assert "Batterie" not in sample().summary()
    assert "Batterie 50 %" in sample(battery=50, on_ac=False).summary()
    assert "en charge" in sample(battery=50, on_ac=True).summary()


def test_cpu_sampler_first_reading_is_zero_and_stays_in_range():
    sampler = CpuSampler()

    first = sampler.sample()
    second = sampler.sample()

    assert first == 0.0  # the first call only primes the baseline
    assert 0.0 <= second <= 100.0


# -- Claude moods vs machine moods -----------------------------------------


def test_no_claude_activity_leaves_the_machine_mood_alone():
    assert combine(Mood.BUSY, None) is Mood.BUSY


def test_a_waiting_session_outranks_a_busy_machine():
    # The whole point: one needs an answer, the other is just weather.
    assert combine(Mood.STRESSED, Mood.WAITING) is Mood.WAITING


def test_waiting_outranks_every_other_claude_state():
    assert claude_mood_for(["working", "waiting", "done"]) is Mood.WAITING


def test_error_outranks_working():
    assert claude_mood_for(["working", "error"]) is Mood.ERROR


def test_thinking_counts_as_working():
    assert claude_mood_for(["thinking"]) is Mood.WORKING


def test_only_idle_sessions_mean_no_claude_mood():
    assert claude_mood_for([]) is None
    assert claude_mood_for(["idle", "idle"]) is None


def test_a_finished_session_still_shows():
    assert claude_mood_for(["done"]) is Mood.DONE
