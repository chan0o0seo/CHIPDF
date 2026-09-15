"""Structured paragraphs <-> Qt text layout, shared by canvas and PNG export."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor

from .model import Paragraph, Run, Style

ALIGN = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}


def char_format(style: Style) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setFontFamilies([style.family])
    fmt.setFontPointSize(style.size)
    fmt.setForeground(QColor(style.color))
    fmt.setFontWeight(QFont.Bold if style.bold else QFont.Normal)
    fmt.setFontItalic(style.italic)
    fmt.setFontUnderline(style.underline)
    fmt.setFontStrikeOut(style.strike)
    return fmt


def populate(document, paragraphs, margin=8):
    document.setUndoRedoEnabled(False)
    document.clear()
    document.setDefaultFont(char_format(paragraphs[0].runs[0].style).font())
    document.setDocumentMargin(margin)
    option = document.defaultTextOption()
    option.setUseDesignMetrics(True)
    document.setDefaultTextOption(option)
    cursor = QTextCursor(document)
    for i, para in enumerate(paragraphs):
        if i:
            cursor.insertBlock()
        fmt = QTextBlockFormat()
        fmt.setAlignment(ALIGN[para.align])
        if para.line_spacing != 1:
            fmt.setLineHeight(para.line_spacing*100, QTextBlockFormat.ProportionalHeight.value)
        fmt.setTopMargin(para.space_before)
        fmt.setBottomMargin(para.space_after)
        cursor.setBlockFormat(fmt)
        for run in para.runs:
            cursor.setCharFormat(char_format(run.style))
            cursor.insertText(run.text)
    document.setUndoRedoEnabled(True)


def extract(document, default_color="#253345") -> list[Paragraph]:
    paragraphs = []
    block = document.begin()
    while block.isValid():
        alignment = block.blockFormat().alignment()
        align = "center" if alignment & Qt.AlignHCenter else "right" if alignment & Qt.AlignRight else "left"
        runs = []
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid():
                fmt = fragment.charFormat()
                font = fmt.font().resolve(document.defaultFont())
                color = default_color if fmt.foreground().style() == Qt.NoBrush else fmt.foreground().color().name()
                style = Style(font.family(), font.pointSizeF(), color, font.weight() >= QFont.Bold,
                              font.italic(), font.underline(), font.strikeOut())
                runs.append(Run(fragment.text(), style))
            it += 1
        if not runs:
            fmt = QTextCursor(block).charFormat()
            font = fmt.font().resolve(document.defaultFont())
            color = default_color if fmt.foreground().style() == Qt.NoBrush else fmt.foreground().color().name()
            runs = [Run("", Style(font.family(), font.pointSizeF(), color, font.bold(), font.italic(), font.underline(), font.strikeOut()))]
        fmt = block.blockFormat()
        spacing = fmt.lineHeight()/100 if fmt.lineHeightType() == QTextBlockFormat.ProportionalHeight.value else 1.0
        paragraphs.append(Paragraph(runs, align, spacing, fmt.topMargin(), fmt.bottomMargin()))
        block = block.next()
    return paragraphs
