TF_CONVERSIONMODE_NATIVE = 0x0001
_MODE_CODES = {"unknown": b"\x00", "alphanumeric": b"\x01", "native": b"\x02"}


def input_mode_pipe_name(sid: str, session_id: int) -> str:
    """Return the per-user, per-session helper pipe name."""
    identity = hashlib.sha256(sid.encode()).hexdigest()[:16]
    return rf"\\.\pipe\yasb-input-mode-{identity}-{session_id}"


def input_mode_key(conversion_mode: int | None, last_mode: str | None = None) -> str:
    """Classify an IMM32 conversion-mode bit field.

    Args:
        conversion_mode: Value returned by the IME window.
        last_mode: Most recent successfully observed mode.
    Returns:
        ``native``, ``alphanumeric``, or ``unknown``.
    """
    if conversion_mode is None:
        return last_mode or "unknown"
    return "native" if conversion_mode & TF_CONVERSIONMODE_NATIVE else "alphanumeric"


def input_mode_target(focus_hwnd: int, caret_hwnd: int, foreground_hwnd: int) -> int:
    """Choose the window whose IME conversion mode should be queried.

    Args:
        focus_hwnd: Focus window from GetGUIThreadInfo.
        caret_hwnd: Caret window from GetGUIThreadInfo.
        foreground_hwnd: Foreground window fallback.
    Returns:
        The first available focus, caret, or foreground window handle.
    """
    return focus_hwnd or caret_hwnd or foreground_hwnd


def input_mode_code(mode: str) -> bytes:
    """Encode an input-mode key for the helper pipe protocol.

    Args:
        mode: Input-mode key.
    Returns:
        Its one-byte protocol representation.
    """
    return _MODE_CODES.get(mode, _MODE_CODES["unknown"])


def mode_from_input_mode_code(value: bytes) -> str:
    """Decode one byte received from the helper pipe.

    Args:
        value: One-byte protocol payload.
    Returns:
        Input-mode key, or ``unknown`` for invalid data.
    """
    return {code: mode for mode, code in _MODE_CODES.items()}.get(value, "unknown")


def format_imm_probe(success: bool, conversion_mode: int | None) -> str:
    """Format an IMM32 conversion-mode diagnostic record.

    Args:
        success: Whether ImmGetConversionStatus succeeded.
        conversion_mode: Raw conversion-mode bit field, when available.
    Returns:
        Compact debug text suitable for the YASB log.
    """
    conversion = "--" if conversion_mode is None else f"0x{conversion_mode:08X}"
    return f"success={success} conversion={conversion} mode={input_mode_key(conversion_mode)}"


import hashlib
