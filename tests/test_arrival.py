from datetime import time

from dobrolap_bot.services.arrival import arrival_price_notice, arrival_requires_price_review


def test_free_arrival_window_is_unambiguous():
    assert not arrival_requires_price_review(time(19, 0))
    assert not arrival_requires_price_review(time(21, 0))
    assert "без доплаты" in arrival_price_notice(time(20, 30))


def test_nonstandard_arrivals_are_sent_for_price_review():
    for value in (time(7, 0), time(15, 0), time(22, 0)):
        assert arrival_requires_price_review(value)
    assert "полного дня" in arrival_price_notice(time(9, 0))
    assert not arrival_requires_price_review(time(9, 0))
    assert "50%" in arrival_price_notice(time(17, 0))
    assert "15%" in arrival_price_notice(time(22, 0))


def test_half_day_arrival_window_is_confirmed():
    assert not arrival_requires_price_review(time(16, 30))
    assert not arrival_requires_price_review(time(18, 59))
    assert "50%" in arrival_price_notice(time(16, 30))
    assert "без доплаты" in arrival_price_notice(time(19, 0))
