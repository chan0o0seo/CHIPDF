"""Structured paragraphs <-> Qt text layout, shared by canvas and PNG export."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextListFormat

from .model import Paragraph, Run, Style

ALIGN = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}


def char_format(style: Style) -> QTextCharFormat:
    fmt = QTextCharFormat()
    fmt.setFontFamilies([style.family])
    fmt.setFontPointSize(style.size)
    # Avoid missing Hangul strokes in Qt's hinted Malgun Gothic rendering.
    fmt.setFontHintingPreference(QFont.PreferNoHinting)
    fmt.setForeground(QColor(style.color))
    fmt.setFontWeight(QFont.Bold if style.bold else QFont.Normal)
    fmt.setFontItalic(style.italic)
    fmt.setFontUnderline(style.underline)
    fmt.setFontStrikeOut(style.strike)
    if style.letter_spacing:
        # Untouched text keeps Qt's default font, which the PDF writer embeds compactly.
        fmt.setFontLetterSpacingType(QFont.PercentageSpacing)
        fmt.setFontLetterSpacing(100 + letter_spacing_percent(style.letter_spacing))
    return fmt


def letter_spacing_percent(value):
    """1/1000 em as a percentage of the advance; exact for full-width Hangul."""
    return value / 10


def letter_spacing_from(fmt):
    if fmt.fontLetterSpacingType() != QFont.PercentageSpacing or fmt.fontLetterSpacing() in (0, 100):
        return 0.0
    return round((fmt.fontLetterSpacing() - 100) * 10, 1)


def populate(document, paragraphs, margin=8):
    document.setUndoRedoEnabled(False)
    document.clear()
    document.setDefaultFont(char_format(paragraphs[0].runs[0].style).font())
    document.setDocumentMargin(margin)
    option = document.defaultTextOption()
    option.setUseDesignMetrics(True)
    document.setDefaultTextOption(option)
    cursor = QTextCursor(document)
    current_list = None
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
        # Consecutive paragraphs of one list style share a list, so numbering continues.
        if para.list_style:
            if current_list is not None and list_style_of(current_list) == para.list_style:
                current_list.add(cursor.block())
            else:
                current_list = cursor.createList(LIST_FORMATS[para.list_style])
        else:
            current_list = None
    document.setUndoRedoEnabled(True)


LIST_FORMATS = {"disc": QTextListFormat.ListDisc, "decimal": QTextListFormat.ListDecimal}


def list_style_of(text_list):
    if text_list is None:
        return ""
    style = text_list.format().style()
    return "decimal" if style == QTextListFormat.ListDecimal else "disc"


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
                              font.italic(), font.underline(), font.strikeOut(), letter_spacing_from(fmt))
                runs.append(Run(fragment.text(), style))
            it += 1
        if not runs:
            fmt = QTextCursor(block).charFormat()
            font = fmt.font().resolve(document.defaultFont())
            color = default_color if fmt.foreground().style() == Qt.NoBrush else fmt.foreground().color().name()
            runs = [Run("", Style(font.family(), font.pointSizeF(), color, font.bold(), font.italic(), font.underline(),
                                  font.strikeOut(), letter_spacing_from(fmt)))]
        fmt = block.blockFormat()
        spacing = fmt.lineHeight()/100 if fmt.lineHeightType() == QTextBlockFormat.ProportionalHeight.value else 1.0
        paragraphs.append(Paragraph(runs, align, spacing, fmt.topMargin(), fmt.bottomMargin(),
                                    list_style_of(block.textList())))
        block = block.next()
    return paragraphs
