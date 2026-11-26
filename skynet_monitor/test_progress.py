import unittest
from progress import estimate


class ProgressTest(unittest.TestCase):
    def test_resume_uses_observed_delta(self):
        samples = []
        p = dict(step=6000, target=10000, updated=100)
        estimate(p, samples, 100)
        self.assertIsNone(p['eta_seconds'])
        p = dict(step=6100, target=10000, updated=160)
        estimate(p, samples, 160)
        self.assertEqual(p['eta_seconds'], 2340)

    def test_stale_and_rollback_suppress_eta(self):
        samples = [(100, 500, 1000), (160, 600, 1000)]
        p = dict(step=600, target=1000, updated=160)
        estimate(p, samples, 500)
        self.assertTrue(p['stale'])
        self.assertIsNone(p['eta_seconds'])
        p = dict(step=200, target=1000, updated=510)
        estimate(p, samples, 510)
        self.assertEqual(len(samples), 1)
        self.assertIsNone(p['eta_seconds'])
