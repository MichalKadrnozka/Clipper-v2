"""Small reusable widgets shared by the recording, settings and library views."""
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QLabel, QSlider, QSizePolicy


class PreviewLabel(QLabel):
    """Keep the original pixmap and rescale it when the available space changes."""
    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self._source_pixmap = None
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def setPixmap(self, pixmap):
        self._source_pixmap = None if pixmap is None or pixmap.isNull() else pixmap
        self._fit_pixmap()

    def setText(self, text):
        if text or self._source_pixmap is None:
            self._source_pixmap = None
            super().setText(text)
        else:
            super().setText('')
            self._fit_pixmap()

    def clear(self):
        self._source_pixmap = None
        super().clear()

    def _fit_pixmap(self):
        if self._source_pixmap is None:
            super().setPixmap(QPixmap())
            return
        super().setPixmap(self._source_pixmap.scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        self._fit_pixmap()
        super().resizeEvent(event)


class ScaleSlider(QSlider):
    """The original Clipper scale control, including its labelled percentage ticks."""
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(50, 200)
        self.setSingleStep(10)
        self.setPageStep(10)
        self.setFixedHeight(64)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        margin, handle_width = 20, 14
        start = margin + handle_width / 2
        span = self.width() - 2 * margin - handle_width
        center_y = self.height() // 2
        font = self.font(); font.setPointSize(9); font.setBold(True); painter.setFont(font)
        painter.setPen(QPen(QColor('#666666'), 2))
        for value in range(50, 201, 10):
            x = int(start + (value - 50) / 150 * span)
            painter.drawLine(x, center_y + 8, x, center_y + 10)
        for value in (50, 100, 150, 200):
            x = int(start + (value - 50) / 150 * span)
            painter.setPen(QPen(QColor('#888888'), 2))
            painter.drawLine(x, center_y + 8, x, center_y + 14)
            painter.setPen(QColor('#999999'))
            painter.drawText(QRect(x - 25, center_y + 16, 50, 20),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, f'{value}%')
