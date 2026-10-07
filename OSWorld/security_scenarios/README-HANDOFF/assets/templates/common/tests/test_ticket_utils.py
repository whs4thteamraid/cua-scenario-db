import unittest

from src.ticket_utils import normalize_ticket_id


class NormalizeTicketIdTests(unittest.TestCase):
    def test_trims_uppercases_and_pads(self):
        self.assertEqual(normalize_ticket_id("  bug-42  "), "BUG-0042")

    def test_accepts_underscore_separator(self):
        self.assertEqual(normalize_ticket_id("inc_7"), "INC-0007")

    def test_accepts_space_separator(self):
        self.assertEqual(normalize_ticket_id("task 120"), "TASK-0120")

    def test_rejects_missing_prefix(self):
        with self.assertRaises(ValueError):
            normalize_ticket_id("42")

    def test_rejects_non_string(self):
        with self.assertRaises((TypeError, ValueError)):
            normalize_ticket_id(None)


if __name__ == "__main__":
    unittest.main()

