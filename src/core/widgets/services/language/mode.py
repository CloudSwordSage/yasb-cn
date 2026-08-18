import ctypes


TF_CONVERSIONMODE_NATIVE = 0x0001
THREAD_MANAGER_COMPARTMENT_IID = "7DCF57AC-18AD-438B-824D-979BFFB74B7C"


def callback_address(callback) -> ctypes.c_void_p:
    """Return a WinAPI callback as a COM vtable function pointer.

    Args:
        callback: A ``WINFUNCTYPE`` callback object.
    Returns:
        Address suitable for a ``c_void_p`` COM vtable slot.
    """
    return ctypes.cast(callback, ctypes.c_void_p)


def input_mode_key(conversion_mode: int | None) -> str:
    """Classify a TSF conversion-mode bit field.

    Args:
        conversion_mode: Value from GUID_COMPARTMENT_KEYBOARD_INPUTMODE_CONVERSION.
    Returns:
        ``native``, ``alphanumeric``, or ``unknown``.
    """
    if conversion_mode is None:
        return "unknown"
    return "native" if conversion_mode & TF_CONVERSIONMODE_NATIVE else "alphanumeric"


def format_probe(hr: int, variant_type: int | None, conversion_mode: int | None) -> str:
    """Format a TSF conversion-compartment diagnostic record.

    Args:
        hr: HRESULT returned by ITfCompartment.GetValue.
        variant_type: VARIANT type tag, when available.
        conversion_mode: Raw conversion-mode bit field, when available.
    Returns:
        Compact debug text suitable for the YASB log.
    """
    conversion = "--" if conversion_mode is None else f"0x{conversion_mode:08X}"
    return f"hr=0x{hr & 0xFFFFFFFF:08X} vt={variant_type} conversion={conversion} mode={input_mode_key(conversion_mode)}"
