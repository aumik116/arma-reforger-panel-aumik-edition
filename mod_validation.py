"""Canonical validation shared by all mod-list write paths."""
import re


def normalize_mod_entry(entry):
    """Return a canonical mod row, or None for an invalid entry."""
    if not isinstance(entry, dict):
        return None
    values = {key: entry.get(key, '') for key in ('modId', 'name', 'version')}
    if any(not isinstance(value, str) for value in values.values()):
        return None
    if any(ord(char) < 32 or ord(char) == 127 for value in values.values() for char in value):
        return None
    mod_id, name, version = (values[key].strip() for key in ('modId', 'name', 'version'))
    if not re.fullmatch(r'[0-9a-fA-F]{1,32}', mod_id) or len(name) > 200:
        return None
    if version and not re.fullmatch(r'[^\s\\"]{1,32}', version):
        return None
    result = {'modId': mod_id.upper()}
    if name:
        result['name'] = name
    if version:
        result['version'] = version
    return result
