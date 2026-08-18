TF_CONVERSIONMODE_NATIVE = 0x0001


def input_mode_key(conversion_mode: int | None) -> str:
    """Classify an IMM32 conversion-mode bit field.

    Args:
        conversion_mode: Value from ImmGetConversionStatus.
    Returns:
        ``native``, ``alphanumeric``, or ``unknown``.
    """
    if conversion_mode is None:
        return "unknown"
    return "native" if conversion_mode & TF_CONVERSIONMODE_NATIVE else "alphanumeric"


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
