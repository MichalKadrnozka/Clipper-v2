import tempfile
import unittest
from pathlib import Path
from clipper.mp4_duration import ContainerTimingError, limit_presentation


class ContainerTimingTests(unittest.TestCase):
    def test_invalid_file_is_not_modified(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'broken.mp4'
            content = b'\x00\x00\x00\x18moov\x00\x00\x00\x10mvhd'
            path.write_bytes(content)
            with self.assertRaises(ContainerTimingError): limit_presentation(path, 1.0)
            self.assertEqual(path.read_bytes(), content)

    def test_invalid_duration_is_rejected(self):
        for value in (0, -1, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ContainerTimingError):
                limit_presentation('unused', value)
