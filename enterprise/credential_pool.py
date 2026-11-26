"""One channel's keys, encoded inside its existing encrypted revision.

Selection is per platform task. This module has no queue, provider client or
database dependency; the governance transaction assigns and freezes the slot.
"""
import json

_PREFIX = 'ice-key-pool-v1:'


def encode_keys(value):
    if not isinstance(value, str):
        raise ValueError('INVALID_CREDENTIAL_SECRET')
    keys = list(dict.fromkeys(line.strip() for line in value.splitlines() if line.strip()))
    if not keys or any('\x00' in key or key.startswith(_PREFIX) for key in keys):
        raise ValueError('INVALID_CREDENTIAL_SECRET')
    encoded = keys[0] if len(keys) == 1 else _PREFIX + json.dumps(keys, separators=(',', ':'))
    if len(encoded) > 8192:
        raise ValueError('INVALID_CREDENTIAL_SECRET')
    return encoded


def decode_keys(value):
    # Existing single-key revisions remain byte-for-byte usable.
    return json.loads(value[len(_PREFIX):]) if value.startswith(_PREFIX) else [value]
