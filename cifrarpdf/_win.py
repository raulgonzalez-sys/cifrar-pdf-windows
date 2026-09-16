"""Prototipos de la API de Windows que usa el backend.

Declarar «restype» y «argtypes» aquí no es cosmético: por omisión ctypes trata
el valor devuelto como un «c_int» de 32 bits, y eso **trunca los HANDLE en
64 bits** — el asa resultante es basura y todo lo que se haga con ella falla de
forma difícil de diagnosticar. Con los prototipos declarados en un solo sitio,
el resto del paquete llama a estas funciones sin pensar en ello.

Este módulo solo se puede importar en Windows (carga kernel32 al importarse),
así que los módulos que lo usan lo importan dentro de la función, no arriba.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
ole32 = ctypes.WinDLL("ole32", use_last_error=True)

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
SYNCHRONIZE = 0x00100000
EVENT_MODIFY_STATE = 0x0002
DETACHED_PROCESS = 0x00000008
CREATE_NO_WINDOW = 0x08000000

kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]

kernel32.OpenMutexW.restype = wintypes.HANDLE
kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]

kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL,
                                  wintypes.LPCWSTR]

kernel32.OpenEventW.restype = wintypes.HANDLE
kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]

kernel32.SetEvent.restype = wintypes.BOOL
kernel32.SetEvent.argtypes = [wintypes.HANDLE]

kernel32.ResetEvent.restype = wintypes.BOOL
kernel32.ResetEvent.argtypes = [wintypes.HANDLE]

kernel32.WaitForSingleObject.restype = wintypes.DWORD
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

kernel32.LocalFree.restype = wintypes.HANDLE
kernel32.LocalFree.argtypes = [wintypes.HANDLE]


class BLOB(ctypes.Structure):
    """DATA_BLOB de la API de protección de datos (DPAPI)."""

    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


crypt32.CryptProtectData.restype = wintypes.BOOL
crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(BLOB), wintypes.LPCWSTR, ctypes.POINTER(BLOB), wintypes.LPVOID,
    wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(BLOB),
]

crypt32.CryptUnprotectData.restype = wintypes.BOOL
crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(BLOB), wintypes.LPVOID, ctypes.POINTER(BLOB), wintypes.LPVOID,
    wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(BLOB),
]


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_byte * 8),
    ]


ole32.CLSIDFromString.restype = ctypes.HRESULT
ole32.CLSIDFromString.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(GUID)]

ole32.CoTaskMemFree.restype = None
ole32.CoTaskMemFree.argtypes = [wintypes.LPVOID]

shell32.SetCurrentProcessExplicitAppUserModelID.restype = ctypes.HRESULT
shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]

shell32.SHGetKnownFolderPath.restype = ctypes.HRESULT
shell32.SHGetKnownFolderPath.argtypes = [
    ctypes.POINTER(GUID), wintypes.DWORD, wintypes.HANDLE,
    ctypes.POINTER(ctypes.c_wchar_p),
]
