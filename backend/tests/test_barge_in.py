"""Tests for BargeInController."""

from __future__ import annotations

from fae.pipecat.barge_in import BargeInController


def test_barge_in_clears_queue_and_stops_playback() -> None:
    ctrl = BargeInController()
    ctrl.start_playback()
    ctrl.enqueue("一句。")
    ctrl.enqueue("两句。")
    assert ctrl.pop_next() == "一句。"

    ctrl.on_user_speech_during_playback()

    assert ctrl.interrupted is True
    assert ctrl.is_playing is False
    assert ctrl.pop_next() is None


def test_reset_clears_interrupt_flag() -> None:
    ctrl = BargeInController()
    ctrl.on_user_speech_during_playback()
    ctrl.reset()
    assert ctrl.interrupted is False
    ctrl.enqueue("ok")
    assert ctrl.pop_next() == "ok"
