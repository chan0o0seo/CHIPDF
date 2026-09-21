"""Platform defaults without importing Qt or changing existing document styles."""
import os
from pathlib import Path
import sys


def default_data_dir():
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/TranslationStudio'
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'TranslationStudio'
    return Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'TranslationStudio'


def default_font_family():
    return 'Apple SD Gothic Neo' if sys.platform == 'darwin' else '맑은 고딕'


def ui_font_families():
    if sys.platform == 'darwin':
        return '"Apple SD Gothic Neo", "Helvetica Neue"'
    return '"Malgun Gothic", "Segoe UI"'
