import unittest

from src.alert_filtering import AlertFilter, SignalRecord


def record(grade="A", decision="WATCH", risk=40, event="event-a", zone="zone-a"):
    return SignalRecord(
        signal_id="sig",
        symbol="SNDK",
        time="2026-08-11T09:00:00",
        price=100.0,
        grade=grade,
        decision=decision,
        impact_score=80,
        opportunity_score=75,
        risk_score=risk,
        entry=100.0,
        stop=95.0,
        targets=(112.0, 125.0),
        reason="test",
        event_fingerprint=event,
        buy_zone=zone,
    )


class AlertFilteringTests(unittest.TestCase):
    def test_a_upgrade_to_s_pushes_again(self):
        alerts = AlertFilter()
        self.assertTrue(alerts.should_push(record("A", "WATCH")).should_push)
        self.assertFalse(alerts.should_push(record("A", "WATCH")).should_push)
        self.assertTrue(alerts.should_push(record("S", "BUY")).should_push)

    def test_watch_to_buy_pushes_again(self):
        alerts = AlertFilter()
        self.assertTrue(alerts.should_push(record("A", "WATCH")).should_push)
        self.assertTrue(alerts.should_push(record("A", "BUY")).should_push)

    def test_b_grade_not_pushed(self):
        self.assertFalse(AlertFilter().should_push(record("B", "WAIT")).should_push)


if __name__ == "__main__":
    unittest.main()

