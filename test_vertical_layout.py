"""Vertical view geometry: native Qt cursor units, Unicode and rich painting."""
import unittest

from test_studio import APP
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QTextDocument

from studio.model import Paragraph, Run, Style
from studio.richtext import populate
from studio.vertical_text import VerticalLayout, grapheme_spans


class VerticalLayoutTests(unittest.TestCase):
    def layout(self, paragraphs, width=180, height=160, margin=8):
        document = QTextDocument()
        populate(document, paragraphs, margin)
        return VerticalLayout(document, width, height, margin)

    def text_layout(self, text, **kwargs):
        return self.layout([Paragraph([Run(text)])], **kwargs)

    def test_columns_read_down_then_left_and_report_overflow(self):
        layout = self.text_layout("가나다라마바사아자차", height=78)
        self.assertGreater(len(layout.columns), 1)
        self.assertEqual(layout.glyphs[0].rect.x(), layout.glyphs[1].rect.x())
        self.assertLess(layout.glyphs[0].rect.y(), layout.glyphs[1].rect.y())
        self.assertLess(layout.columns[1].rect.x(), layout.columns[0].rect.x())
        self.assertFalse(layout.overflow)
        self.assertTrue(self.text_layout("가나다라마바사아자차", width=45, height=78).overflow)
        self.assertTrue(self.text_layout("가", height=20).overflow)

    def test_unicode_clusters_use_qt_utf16_positions(self):
        text = "가👨‍👩‍👧‍👦e\u0301🇰🇷나"
        spans = list(grapheme_spans(text))
        self.assertEqual([value[2] for value in spans], ["가", "👨‍👩‍👧‍👦", "e\u0301", "🇰🇷", "나"])
        self.assertEqual([(value[0], value[1]) for value in spans], [(0, 1), (1, 12), (12, 14), (14, 18), (18, 19)])
        layout = self.text_layout(text, height=500)
        self.assertEqual(layout.boundaries, (0, 1, 12, 14, 18, 19))
        self.assertEqual(layout.move_cursor(1, "down"), 12)
        self.assertEqual(layout.move_cursor(12, "up"), 1)
        self.assertIn(layout.normalize_position(4), layout.boundaries)
        for glyph in layout.glyphs:
            self.assertIn(layout.hit_test(glyph.rect.center()), (glyph.start, glyph.end))

    def test_empty_and_trailing_paragraphs_have_real_carets(self):
        layout = self.layout([Paragraph([Run("가")]), Paragraph([Run("")]), Paragraph([Run("나")]), Paragraph([Run("")])])
        self.assertEqual(len(layout.columns), 4)
        self.assertEqual(layout.boundaries, tuple(range(6)))
        self.assertEqual([column.start for column in layout.columns], [0, 2, 3, 5])
        self.assertLess(layout.caret_rect(5).x(), layout.caret_rect(3).x())
        self.assertEqual(layout.hit_test(layout.caret_rect(5).center()), 5)
        empty = self.text_layout("")
        self.assertEqual(empty.boundaries, (0,))
        self.assertEqual(empty.move_cursor(0, "down"), 0)
        self.assertGreater(empty.caret_rect(0).width(), 0)

    def test_visual_arrow_keys_and_home_end(self):
        layout = self.text_layout("가나다라마바", height=102)
        self.assertEqual(len(layout.columns), 2)
        self.assertEqual(layout.move_cursor(1, "left"), 4)
        self.assertEqual(layout.move_cursor(4, "right"), 1)
        self.assertEqual(layout.move_cursor(4, "home"), 3)
        self.assertEqual(layout.move_cursor(4, "end"), 6)
        self.assertEqual(layout.move_cursor(0, "right"), 0)
        self.assertEqual(layout.move_cursor(6, "left"), 6)
        self.assertEqual(layout.hit_test(QPointF(-500, 500)), 6)

    def test_soft_break_starts_column_and_keeps_separator_selectable(self):
        layout = self.layout([Paragraph([Run("A\u2028B")], line_spacing=1.5,
                                        space_before=7, space_after=11)])
        self.assertEqual([glyph.text for glyph in layout.glyphs], ["A", "B"])
        self.assertEqual(len(layout.columns), 2)
        self.assertEqual(layout.boundaries, (0, 1, 2, 3))
        self.assertEqual(layout.columns[0].separator, 1)
        self.assertLess(layout.caret_rect(2).x(), layout.caret_rect(1).x())
        self.assertEqual(layout.caret_rect(0).y(), layout.caret_rect(2).y())
        self.assertAlmostEqual(layout.columns[0].rect.x() - layout.columns[1].rect.x(),
                               layout.columns[0].width * 1.5)
        self.assertEqual(layout.move_cursor(1, "down"), 2)
        self.assertEqual(layout.move_cursor(2, "up"), 1)
        self.assertEqual(layout.move_cursor(0, "left"), 2)
        self.assertEqual(layout.hit_test(layout.caret_rect(2).center()), 2)
        image = QImage(180, 160, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        layout.paint(painter, 1, 2)
        painter.end()
        sample = layout.caret_rect(1).topLeft() + QPointF(1, 1)
        self.assertEqual(image.pixelColor(int(sample.x()), int(sample.y())).name(), "#3478c4")
        self.assertEqual(layout.document.toPlainText(), "A\nB")

    def test_consecutive_trailing_soft_breaks_preserve_empty_columns(self):
        layout = self.text_layout("A\u2028\u2028")
        self.assertEqual(len(layout.columns), 3)
        self.assertEqual([column.start for column in layout.columns], [0, 2, 3])
        self.assertEqual([column.separator for column in layout.columns], [1, 2, None])
        self.assertEqual(layout.boundaries, (0, 1, 2, 3))
        self.assertEqual(layout.move_cursor(2, "down"), 3)
        self.assertEqual(layout.move_cursor(3, "up"), 2)
        self.assertLess(layout.caret_rect(3).x(), layout.caret_rect(2).x())
        self.assertEqual(layout.hit_test(layout.caret_rect(3).center()), 3)
        self.assertEqual([glyph.text for glyph in layout.glyphs], ["A"])

    def test_paragraph_alignment_spacing_and_rich_size(self):
        left = self.layout([Paragraph([Run("가나")], align="left")])
        center = self.layout([Paragraph([Run("가나")], align="center")])
        right = self.layout([Paragraph([Run("가나")], align="right")])
        self.assertLess(left.caret_rect(0).y(), center.caret_rect(0).y())
        self.assertLess(center.caret_rect(0).y(), right.caret_rect(0).y())
        self.assertAlmostEqual(right.caret_rect(2).y(), 152)
        normal = self.layout([Paragraph([Run("가나다라마바")])], height=102)
        spaced = self.layout([Paragraph([Run("가나다라마바")], line_spacing=1.5)], height=102)
        self.assertAlmostEqual(normal.columns[0].rect.x(), spaced.columns[0].rect.x())
        self.assertLess(spaced.columns[1].rect.x(), normal.columns[1].rect.x())
        paragraphs = self.layout([Paragraph([Run("가")], space_before=7, space_after=11), Paragraph([Run("나")], space_before=5)])
        self.assertAlmostEqual(paragraphs.columns[0].rect.right(), 165)
        self.assertAlmostEqual(paragraphs.columns[0].rect.left() - paragraphs.columns[1].rect.right(), 16)
        sized = self.layout([Paragraph([Run("가", Style(size=12)), Run("나", Style(size=30))])])
        self.assertGreater(sized.glyphs[1].advance, sized.glyphs[0].advance * 2)

    def test_paint_preserves_document_and_rich_colors_selection(self):
        red = Style(color="#ff0000", underline=True)
        blue = Style(color="#0000ff", bold=True, strike=True)
        layout = self.layout([Paragraph([Run("가「、", red), Run("나ー」", blue)])], height=250)
        before = layout.document.toHtml()
        image = QImage(180, 250, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        layout.paint(painter)
        painter.end()
        colors = [image.pixelColor(x, y) for x in range(image.width()) for y in range(image.height())]
        self.assertTrue(any(c.red() > 200 and c.blue() < 40 for c in colors))
        self.assertTrue(any(c.blue() > 200 and c.red() < 40 for c in colors))
        painter = QPainter(image)
        layout.paint(painter, 0, 1)
        painter.end()
        sample = layout.glyphs[0].rect.topLeft() + QPointF(1, 1)
        self.assertEqual(image.pixelColor(int(sample.x()), int(sample.y())).name(), "#3478c4")
        self.assertEqual(layout.document.toHtml(), before)


if __name__ == "__main__":
    unittest.main()
