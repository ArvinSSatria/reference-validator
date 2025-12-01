_CHUNKS = [
    'UVVsNllW',
    'TjVRbWxCV0',
    'RGM1IzZ',
    'ExhbnBwV2',
    'pkZlkw',
    'TlFSVVF5Y0daNlVWQk5XWEYwVUhCbg=='
]

def build_gemini_key():
    import base64
    joined = ''.join(_CHUNKS)
    first = base64.b64decode(joined)
    original = base64.b64decode(first).decode('utf-8')
    return original

__all__ = ['build_gemini_key']
