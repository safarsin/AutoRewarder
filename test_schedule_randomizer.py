import unittest
from datetime import datetime

from schedule_randomizer import (
    DEFAULT_DEADLINE_HOUR,
    QPH_MAX,
    QPH_MIN,
    AccountRoll,
    available_duration_hours,
    random_search_split,
    randomized_queries_per_hour,
)


class SearchSplitTests(unittest.TestCase):
    def test_random_search_split_uses_one_total_and_splits_between_pc_and_mobile(self):
        class FixedRng:
            def __init__(self):
                self.calls = []

            def randint(self, minimum, maximum):
                self.calls.append((minimum, maximum))
                if len(self.calls) == 1:
                    return maximum
                return maximum

        rng = FixedRng()

        pc, mobile = random_search_split(rng)

        self.assertEqual((pc, mobile), (20, 0))
        self.assertEqual(
            rng.calls,
            [(3, 20), (0, 20)],
        )
        self.assertGreaterEqual(pc + mobile, 3)
        self.assertLessEqual(pc + mobile, 20)


class SchedulePacingTests(unittest.TestCase):
    def test_low_volume_can_use_one_qph(self):
        roll = AccountRoll("test", None, {}, {}, 3, 0, 3)

        self.assertEqual(randomized_queries_per_hour(roll, FixedRng(0)), 1)

    def test_qph_stays_within_low_volume_bounds(self):
        roll = AccountRoll("test", None, {}, {}, 20, 0, 2.15)

        self.assertEqual(randomized_queries_per_hour(roll, FixedRng(3)), QPH_MAX)
        self.assertEqual((QPH_MIN, QPH_MAX), (1, 10))

    def test_default_deadline_is_ten_pm(self):
        self.assertEqual(DEFAULT_DEADLINE_HOUR, 22)
        self.assertEqual(
            available_duration_hours(datetime(2026, 7, 30, 6, 0), 22, 0, 15),
            15.75,
        )


class FixedRng:
    def __init__(self, value):
        self.value = value

    def randint(self, minimum, maximum):
        return self.value


if __name__ == "__main__":
    unittest.main()
