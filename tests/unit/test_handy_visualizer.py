import os
import sys
import unittest

# Add project root to import path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from src.audio.handy_visualizer import HandyAudioVisualizer, NUMPY_AVAILABLE

if NUMPY_AVAILABLE:
    import numpy as np


@unittest.skipUnless(NUMPY_AVAILABLE, "NumPy is required for visualizer tests")
class TestHandyAudioVisualizer(unittest.TestCase):
    def setUp(self):
        self.visualizer = HandyAudioVisualizer(sample_rate=16000, window_size=512, bucket_count=16)

    def test_feed_requires_full_window_before_emitting_levels(self):
        partial = np.zeros(480, dtype=np.int16)
        self.assertIsNone(self.visualizer.feed(partial))

        levels = self.visualizer.feed(partial)
        self.assertIsInstance(levels, list)
        self.assertEqual(len(levels), 16)

    def test_levels_are_bounded(self):
        frame = np.random.randint(-32768, 32767, size=512, dtype=np.int16)
        levels = self.visualizer.feed(frame)
        self.assertEqual(len(levels), 16)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in levels))

    def test_reset_clears_state(self):
        frame = np.random.randint(-32768, 32767, size=512, dtype=np.int16)
        self.visualizer.feed(frame)
        self.visualizer.reset()
        self.assertEqual(self.visualizer.last_levels, [0.0] * 16)
        self.assertIsNone(self.visualizer.feed(np.zeros(256, dtype=np.int16)))


if __name__ == "__main__":
    unittest.main()
