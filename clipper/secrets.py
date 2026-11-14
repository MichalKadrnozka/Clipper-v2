"""Encrypt remembered OBS credentials with the current Windows user account."""
import base64
import sys

def _crypt(data: bytes, decrypt: bool) -> bytes:
    if sys.platform != 'win32':
        raise RuntimeError('Credential storage is only available on Windows')
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_byte))]
    payload = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(payload, ctypes.POINTER(ctypes.c_byte)))
    result = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        fn = crypt.CryptUnprotectData
    else:
        fn = crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    try: return ctypes.string_at(result.pbData, result.cbData)
    finally: kernel.LocalFree(result.pbData)

def protect(text: str) -> str:
    return base64.b64encode(_crypt(text.encode('utf-8'), False)).decode('ascii')

def unprotect(text: str) -> str:
    return _crypt(base64.b64decode(text, validate=True), True).decode('utf-8')
