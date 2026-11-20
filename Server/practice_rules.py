"""The teacher's default practice selection references a named rule file."""
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def default_rule(directory):
    try:
        name = (Path(directory) / '.practice-default').read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        return None
    if name == Path(name).name and name.lower().endswith('.json') and (Path(directory) / name).is_file():
        return name
    return None


def set_default_rule(directory, name):
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=directory, delete=False) as tmp:
        tmp.write(name)
    try:
        os.replace(tmp.name, Path(directory) / '.practice-default')
    finally:
        Path(tmp.name).unlink(missing_ok=True)
