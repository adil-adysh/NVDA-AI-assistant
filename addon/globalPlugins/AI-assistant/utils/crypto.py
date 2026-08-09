# -*- coding: utf-8 -*-
"""Transparent encryption for sensitive config values using Windows DPAPI.

DPAPI (Data Protection API) encrypts data so that only the current Windows user
on the current machine can decrypt it.  This module calls ``crypt32.dll``
directly via Python's built-in ``ctypes`` — no extra dependencies required.
``win32crypt`` is **not** used.

Encrypted values are stored in YAML as: ``!!enc:<base64-blob>``
Plaintext values (migrated on next save) are stored as normal strings.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
from typing import Optional

from logHandler import log

ENCRYPTED_PREFIX = "!!enc:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1

# ---------------------------------------------------------------------------
#  Lazy ctypes bindings for crypt32.dll  (Windows DPAPI)
#  Loaded on first use to avoid blocking NVDA's main thread at import time.
# ---------------------------------------------------------------------------

_crypto_available: Optional[bool] = None

# Cached function pointers (set once during _init_dpapi)
_CryptProtectData = None
_CryptUnprotectData = None
_LocalFree = None


class _DATA_BLOB(ctypes.Structure):
	_fields_ = [
		("cbData", ctypes.wintypes.DWORD),
		("pbData", ctypes.POINTER(ctypes.c_byte)),
	]


# Lazy-init singleton: DPAPI function pointers are cached on first use.
# pylint: disable=global-statement


def _init_dpapi() -> bool:
	"""One-time initialisation of DPAPI function pointers.

	Returns True when successful, False otherwise.
	"""
	global _crypto_available, _CryptProtectData, _CryptUnprotectData, _LocalFree
	if _crypto_available is not None:
		return _crypto_available

	try:
		crypt32 = ctypes.windll.crypt32

		_CryptProtectData = crypt32.CryptProtectData
		_CryptProtectData.argtypes = [
			ctypes.POINTER(_DATA_BLOB),  # pDataIn
			ctypes.wintypes.LPCWSTR,  # szDataDescr
			ctypes.POINTER(_DATA_BLOB),  # pOptionalEntropy
			ctypes.c_void_p,  # pvReserved
			ctypes.c_void_p,  # pPromptStruct
			ctypes.wintypes.DWORD,  # dwFlags
			ctypes.POINTER(_DATA_BLOB),  # pDataOut
		]
		_CryptProtectData.restype = ctypes.wintypes.BOOL

		_CryptUnprotectData = crypt32.CryptUnprotectData
		_CryptUnprotectData.argtypes = [
			ctypes.POINTER(_DATA_BLOB),  # pDataIn
			ctypes.POINTER(ctypes.wintypes.LPWSTR),  # ppszDataDescr
			ctypes.POINTER(_DATA_BLOB),  # pOptionalEntropy
			ctypes.c_void_p,  # pvReserved
			ctypes.c_void_p,  # pPromptStruct
			ctypes.wintypes.DWORD,  # dwFlags
			ctypes.POINTER(_DATA_BLOB),  # pDataOut
		]
		_CryptUnprotectData.restype = ctypes.wintypes.BOOL

		_LocalFree = ctypes.windll.kernel32.LocalFree
		_LocalFree.argtypes = [ctypes.c_void_p]
		_LocalFree.restype = ctypes.c_void_p

		_crypto_available = True
		return True
	except Exception:
		log.warning(
			"Windows DPAPI (crypt32.dll) not available – API keys will be stored in plain text.",
			exc_info=True,
		)
		_crypto_available = False
		return False


def _make_blob(data: bytes) -> _DATA_BLOB:
	"""Build a DATA_BLOB from *data*.

	Fields are declared on the ctypes ``_DATA_BLOB._fields_`` class attribute;
	the blob instance is populated here instead of ``__init__``. The returned
	blob owns Python-allocated memory — do **not** pass it to ``LocalFree``.
	"""
	# pylint: disable=attribute-defined-outside-init
	blob = _DATA_BLOB()
	blob.cbData = len(data)
	blob.pbData = (ctypes.c_byte * len(data))(*data)
	return blob


def _blob_to_bytes(blob: _DATA_BLOB) -> bytes:
	"""Read bytes from a DATA_BLOB (heap-allocated by DPAPI)."""
	return ctypes.string_at(blob.pbData, blob.cbData)


def _free_dpapi_blob(blob: _DATA_BLOB) -> None:
	"""Free a DATA_BLOB that was allocated **by DPAPI** (output blob).

	Do **not** call this on blobs created via ``_make_blob`` — those use
	Python-managed memory.
	"""
	if blob.pbData and _LocalFree is not None:
		_LocalFree(blob.pbData)
		blob.pbData = None
		blob.cbData = 0


def encrypt_value(plaintext: str) -> str:
	"""Encrypt *plaintext* and return a ``!!enc:...`` prefixed string.

	If DPAPI is unavailable the plaintext is returned as-is (no prefix).
	"""
	if not plaintext:
		return plaintext

	if not _init_dpapi():
		return plaintext

	data_in = _make_blob(plaintext.encode("utf-8"))
	data_out = _DATA_BLOB()

	try:
		ok = _CryptProtectData(
			ctypes.byref(data_in),
			"NVDA AI Assistant API key",
			None,
			None,
			None,
			_CRYPTPROTECT_UI_FORBIDDEN,
			ctypes.byref(data_out),
		)
		if not ok:
			raise ctypes.WinError()
		encrypted_bytes = _blob_to_bytes(data_out)
		encoded = base64.b64encode(encrypted_bytes).decode("ascii")
		return f"{ENCRYPTED_PREFIX}{encoded}"
	except Exception:
		log.exception("Failed to encrypt config value – storing in plain text.")
		return plaintext
	finally:
		# data_in uses Python-managed memory — do NOT LocalFree it.
		_free_dpapi_blob(data_out)


def decrypt_value(stored: str) -> str:
	"""If *stored* starts with ``!!enc:``, decrypt it.  Otherwise return as-is."""
	if not stored or not stored.startswith(ENCRYPTED_PREFIX):
		return stored

	if not _init_dpapi():
		log.warning("Windows DPAPI not available – cannot decrypt stored API key.")
		return stored

	b64_part = stored[len(ENCRYPTED_PREFIX) :]
	try:
		blob_bytes = base64.b64decode(b64_part)
	except Exception:
		log.exception("Failed to base64-decode encrypted value – returning raw.")
		return stored

	data_in = _make_blob(blob_bytes)
	data_out = _DATA_BLOB()
	desc_ptr = ctypes.wintypes.LPWSTR()

	try:
		ok = _CryptUnprotectData(
			ctypes.byref(data_in),
			ctypes.byref(desc_ptr),
			None,
			None,
			None,
			_CRYPTPROTECT_UI_FORBIDDEN,
			ctypes.byref(data_out),
		)
		if not ok:
			raise ctypes.WinError()
		plaintext_bytes = _blob_to_bytes(data_out)
		return plaintext_bytes.decode("utf-8", errors="replace")
	except Exception:
		log.exception("Failed to decrypt config value – returning raw stored value.")
		return stored
	finally:
		# data_in uses Python-managed memory — do NOT LocalFree it.
		_free_dpapi_blob(data_out)
		if desc_ptr and desc_ptr.value:
			_LocalFree(desc_ptr)


def is_encrypted(stored: str) -> bool:
	"""Return True when *stored* starts with the encrypted prefix."""
	return bool(stored) and stored.startswith(ENCRYPTED_PREFIX)


# ---------------------------------------------------------------------------
# Sensitive-key detection – used by the YAML store to decide which keys
# need encryption / decryption.
# ---------------------------------------------------------------------------

_SENSITIVE_KEY_SUFFIXES: tuple[str, ...] = (
	"ApiKey",
	"ApiToken",
)


def is_sensitive_key(key: str) -> bool:
	"""Return True when *key* looks like an API credential."""
	return key.endswith(_SENSITIVE_KEY_SUFFIXES)
