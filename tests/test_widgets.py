import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QApplication
from clipper.widgets import PreviewLabel, ScaleSlider


class WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_empty_preview_can_clear_and_resize(self):
        label = PreviewLabel('Náhled')
        label.resize(320, 180)
        label.setPixmap(QPixmap())
        label.resize(640, 360)
        self.assertIsNone(label._source_pixmap)
        self.assertTrue(label.pixmap().isNull())

    def test_message_clear_does_not_discard_source_image(self):
        label = PreviewLabel()
        image = QImage(64, 36, QImage.Format.Format_RGB32); image.fill(0xffff7300)
        label.setPixmap(QPixmap.fromImage(image))
        label.setText('')
        self.assertIsNotNone(label._source_pixmap)
        label.resize(320, 180)
        self.assertFalse(label.pixmap().isNull())
        label.setText('Chyba')
        self.assertIsNone(label._source_pixmap)

    def test_scale_slider_keeps_original_range(self):
        slider = ScaleSlider()
        self.assertEqual((slider.minimum(), slider.maximum()), (50, 200))
        self.assertEqual(slider.singleStep(), 10)
