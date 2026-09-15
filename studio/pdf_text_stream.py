"""Preserve PDF graphics while removing native text, including text clips.

The old localizer supported glyph-clipped paint. Dropping a text object alone
does not remove the clip copied onto later PDFium path/image objects. This
reader rewrites a disposable single-page copy before PDFium renders it.
"""
from contextlib import closing
from io import BytesIO

from .pdf_background import _check_cancel

SHOW = {b'Tj', b'TJ', b"'", b'"'}
PAINT_PATH = {b'f', b'F', b'f*', b'B', b'B*', b'b', b'b*', b'S', b's'}
PAINT_OTHER = {b'Do', b'sh', b'INLINE IMAGE'}
MAX_OPS = 500_000


class UnsupportedText(Exception):
    pass


class TextlessPdf:
    """Read a source once; each requested page is edited in a private writer."""
    def __init__(self, source):
        from pypdf import PdfReader
        self.reader = PdfReader(source)

    def page_bytes(self, index, cancelled=None):
        from pypdf import PdfWriter
        from pypdf.generic import ContentStream, NameObject
        _check_cancel(cancelled)
        writer = PdfWriter()
        page = writer.add_page(self.reader.pages[index])
        forms = {}
        removed, budget = 0, MAX_OPS

        def strip(container, mode=0, depth=0):
            nonlocal removed, budget
            if depth > 32:
                raise UnsupportedText('nested PDF graphics')
            stream = container.get_contents() if depth == 0 else container
            if stream is None:
                return
            operations = ContentStream(stream, writer)
            budget -= len(operations.operations)
            if budget < 0:
                raise UnsupportedText('PDF operation limit')
            state = {'mode': mode, 'clip': False}
            stack, result = [], []
            in_text, pending_clip = False, False
            for offset, (operands, op) in enumerate(operations.operations):
                if offset % 256 == 0:
                    _check_cancel(cancelled)
                if op == b'q':
                    stack.append(state.copy())
                elif op == b'Q':
                    if not stack:
                        raise UnsupportedText('unbalanced PDF graphics')
                    state = stack.pop()
                elif op == b'BT':
                    if in_text:
                        raise UnsupportedText('nested PDF text')
                    in_text, pending_clip = True, False
                elif op == b'ET':
                    in_text = False
                    state['clip'] |= pending_clip
                    pending_clip = False
                elif op == b'Tr':
                    if len(operands) != 1 or int(operands[0]) not in range(8):
                        raise UnsupportedText('unknown text mode')
                    state['mode'] = int(operands[0])
                elif op in SHOW:
                    if not in_text:
                        raise UnsupportedText('text outside BT')
                    removed += state['mode'] != 3
                    pending_clip |= state['mode'] >= 4
                    # Every text show is removed; other text/graphics state
                    # operators stay so subsequent vector colors/CTMs survive.
                    continue
                if state['clip'] and op in PAINT_PATH:
                    result.append(([], b'n'))  # Clear the path without painting.
                    continue
                if state['clip'] and op in PAINT_OTHER:
                    continue
                if op == b'Do' and operands:
                    resources = container.get('/Resources')
                    xobjects = resources.get_object().get('/XObject') if resources else None
                    obj = xobjects.get_object().get(operands[0]) if xobjects else None
                    if obj:
                        obj = obj.get_object()
                        if obj.get('/Subtype') == '/Form':
                            key = id(obj)
                            prior = forms.get(key)
                            if prior is not None and prior != state['mode']:
                                raise UnsupportedText('shared Form with different text modes')
                            if prior is None:
                                forms[key] = state['mode']
                                strip(obj, state['mode'], depth + 1)
                result.append((operands, op))
            if stack or in_text:
                raise UnsupportedText('unbalanced PDF stream')
            operations.operations = result
            if depth == 0:
                container.replace_contents(operations)
            else:
                # ContentStream data is uncompressed. Preserve the Form's
                # resources, matrix and bounds, replacing only its encoding.
                container._data = operations.get_data()
                for key in ('/Filter', '/DecodeParms'):
                    if key in container:
                        del container[NameObject(key)]

        try:
            strip(page)
        except (UnsupportedText, ValueError, TypeError, KeyError, OverflowError):
            return None
        if not removed:
            return None
        output = BytesIO()
        writer.write(output)
        _check_cancel(cancelled)
        return output.getvalue(), removed

    def render(self, index, scale, cancelled=None):
        import pypdfium2 as pdfium
        cleaned = self.page_bytes(index, cancelled)
        if cleaned is None:
            return None
        with pdfium.PdfDocument(cleaned[0]) as document, closing(document[0]) as page:
            _check_cancel(cancelled)
            with closing(page.render(scale=scale)) as bitmap:
                image = bitmap.to_pil()
                output = BytesIO()
                image.save(output, 'PNG')
        _check_cancel(cancelled)
        return output.getvalue(), cleaned[1]
