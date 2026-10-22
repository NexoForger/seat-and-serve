"""Lossless retail barcode validation shared by form and relay."""

import unicodedata


def normalize(value):
    if value is None:
        return ''
    if not isinstance(value, str) or any(unicodedata.category(char) == "Cc" for char in value):
        raise ValueError('Barcode must be text without control characters')
    value = value.strip()
    if len(value) > 140:
        raise ValueError('Barcode must contain at most 140 characters')
    return value

