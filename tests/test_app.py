import unittest

from app import generate_reply_variants


class ReplyGeneratorTests(unittest.TestCase):
    def test_generate_three_replies(self):
        replies = generate_reply_variants("Acme Spa", "Friendly staff and clean lobby", 5, "warm")
        self.assertEqual(3, len(replies))
        self.assertTrue(all("Acme Spa" in reply for reply in replies))

    def test_negative_review_has_recovery_language(self):
        replies = generate_reply_variants("Acme Spa", "Rude service and long wait", 2, "professional")
        self.assertTrue(any("make this right" in r.lower() or "improve" in r.lower() for r in replies))


if __name__ == "__main__":
    unittest.main()
