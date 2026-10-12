"""Recognize local sources that the document importer can open."""
from pathlib import Path

from .document_io import IMAGE_EXTENSIONS


def dropped_paths(mime):
    urls = mime.urls()
    if not urls or len(urls) > 200 or not all(url.isLocalFile() for url in urls):
        return []
    paths = [url.toLocalFile() for url in urls]
    sources = [Path(path) for path in paths]
    if len(sources) == 1 and sources[0].is_dir():
        return paths
    for source in sources:
        if not source.is_file():
            return []
        if source.name.lower().endswith(('.twproj', '.twproj.bak')):
            if len(sources) != 1:
                return []
        elif source.suffix.lower() not in IMAGE_EXTENSIONS | {'.pdf'}:
            return []
    return paths
