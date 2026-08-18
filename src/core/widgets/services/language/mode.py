TF_CONVERSIONMODE_NATIVE = 0x0001


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
