_SALT = b"skripsi"
_XOR_ARRAY = [
    50, 2, 8, 8, 35, 10, 43, 26, 42, 42, 88, 7, 52, 28, 57, 3, 10, 26, 53,
    69, 54, 16, 40, 34, 44, 52, 65, 27, 20, 19, 33, 35, 36, 50, 3, 29, 0,
    3, 14
]

def build_gemini_key():
    out_bytes = bytearray()
    salt_len = len(_SALT)
    for i, v in enumerate(_XOR_ARRAY):
        orig = v ^ _SALT[i % salt_len]
        out_bytes.append(orig)
    return out_bytes.decode('utf-8')

__all__ = ["build_gemini_key"]
