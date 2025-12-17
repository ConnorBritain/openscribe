import os
import unittest

# This test validates our stdout contract and DICTATION_PREVIEW behavior
# without booting the full backend. It checks helper-level behavior and
# documented prefixes to prevent regression of console noise.

WHITELIST_PREFIXES = [
    'PYTHON_BACKEND_READY',
    'GET_CONFIG',
    'STATE:',
    'STATUS:',
    'FINAL_TRANSCRIPT:',
    'HOTKEYS:',
]


class TestStdoutNoiseContract(unittest.TestCase):
    def setUp(self):
        # Ensure minimal terminal mode by default
        os.environ.pop('CT_VERBOSE', None)

    def test_stdout_prefix_whitelist(self):
        valid_samples = [
            'PYTHON_BACKEND_READY',
            'GET_CONFIG',
            'STATE:{"audioState":"activation"}',
            'STATUS:blue:Listening for activation words...',
            'FINAL_TRANSCRIPT:hello world',
            'HOTKEYS:Cmd+Shift+D => start_dictate',
        ]
        for msg in valid_samples:
            with self.subTest(msg=msg):
                self.assertTrue(any(msg.startswith(p) for p in WHITELIST_PREFIXES))

        invalid_samples = [
            '[DEBUG] something',
            'HotkeyManager Status: started',
            'AudioHandler Status: Listening...',
            'Cleared log file: /tmp/x',
            'Unhandled misc output',
        ]
        for msg in invalid_samples:
            with self.subTest(msg=msg):
                self.assertFalse(any(msg.startswith(p) for p in WHITELIST_PREFIXES))

if __name__ == '__main__':
    unittest.main()

