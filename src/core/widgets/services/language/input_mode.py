import ctypes
import logging
import uuid
from ctypes import wintypes

from PyQt6.QtCore import QObject, pyqtSignal

from core.widgets.services.language.mode import THREAD_MANAGER_COMPARTMENT_IID, callback_address, format_probe, input_mode_key


_S_OK = 0
_VT_I4 = 3
_VT_UI4 = 19
logger = logging.getLogger("input_mode")


class _Guid(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, value: str):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class _VariantValue(ctypes.Union):
    _fields_ = [("lVal", ctypes.c_long), ("ulVal", wintypes.DWORD)]


class _Variant(ctypes.Structure):
    _fields_ = [
        ("vt", wintypes.WORD),
        ("wReserved1", wintypes.WORD),
        ("wReserved2", wintypes.WORD),
        ("wReserved3", wintypes.WORD),
        ("value", _VariantValue),
    ]


class _SinkObject(ctypes.Structure):
    _fields_ = [("vtable", ctypes.POINTER(ctypes.c_void_p))]


_GUID_CONVERSION = _Guid.parse("CCF05DD8-4A87-11D7-A6E0-00065B84435C")
_IID_COMPARTMENT_MANAGER = _Guid.parse(THREAD_MANAGER_COMPARTMENT_IID)
_IID_SOURCE = _Guid.parse("4EA48A35-60AE-446F-8FD6-E6A8D82459F7")
_IID_COMPARTMENT_EVENT_SINK = _Guid.parse("743ABD5F-F26D-48DF-8CC5-238492419B64")


def _call(pointer: ctypes.c_void_p, index: int, prototype, *args):
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return prototype(vtable[index])(pointer, *args)


class _CompartmentEventSink:
    def __init__(self, changed) -> None:
        self._changed = changed
        callback = ctypes.WINFUNCTYPE
        self._query = callback(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p))(
            self._query_interface
        )
        self._add_ref = callback(wintypes.ULONG, ctypes.c_void_p)(lambda _this: 1)
        self._release = callback(wintypes.ULONG, ctypes.c_void_p)(lambda _this: 1)
        self._on_change = callback(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_Guid))(self._on_compartment_change)
        self._vtable = (ctypes.c_void_p * 4)(
            callback_address(self._query),
            callback_address(self._add_ref),
            callback_address(self._release),
            callback_address(self._on_change),
        )
        self._object = _SinkObject(ctypes.cast(self._vtable, ctypes.POINTER(ctypes.c_void_p)))
        self.pointer = ctypes.cast(ctypes.pointer(self._object), ctypes.c_void_p)

    def _query_interface(self, this, _iid, output) -> int:
        output[0] = this
        return _S_OK

    def _on_compartment_change(self, _this, _guid) -> int:
        self._changed()
        return _S_OK


class InputModeMonitor(QObject):
    """Watch the TSF conversion-mode compartment without polling."""

    changed = pyqtSignal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread_manager = ctypes.c_void_p()
        self._compartment_manager = ctypes.c_void_p()
        self._compartment = ctypes.c_void_p()
        self._source = ctypes.c_void_p()
        self._cookie = wintypes.DWORD()
        self._sink = _CompartmentEventSink(self._emit_current)
        self._active = False
        self._start()

    def current(self) -> str:
        """Return the current conversion-mode label key."""
        if not self._compartment.value:
            logger.debug("input_mode: compartment unavailable")
            return "unknown"
        value = _Variant()
        hr = _call(self._compartment, 4, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_Variant)), ctypes.byref(value))
        conversion = value.value.ulVal if value.vt in (_VT_I4, _VT_UI4) else None
        logger.debug("input_mode: %s", format_probe(hr, value.vt, conversion))
        if hr < 0 or value.vt not in (_VT_I4, _VT_UI4):
            return "unknown"
        return input_mode_key(conversion)

    def close(self) -> None:
        """Unsubscribe and release TSF interfaces."""
        if self._active:
            _call(self._source, 4, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.DWORD), self._cookie)
            _call(self._thread_manager, 4, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p))
            self._active = False
        for pointer in (self._source, self._compartment, self._compartment_manager, self._thread_manager):
            if pointer.value:
                _call(pointer, 2, ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p))
                pointer.value = None

    def _start(self) -> None:
        try:
            create = ctypes.WinDLL("msctf").TF_CreateThreadMgr
            create.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
            create.restype = ctypes.c_long
            if not self._succeeded("TF_CreateThreadMgr", create(ctypes.byref(self._thread_manager))):
                return
            client_id = wintypes.DWORD()
            if not self._succeeded("ITfThreadMgr.Activate", _call(self._thread_manager, 3, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)), ctypes.byref(client_id))):
                return
            if not self._succeeded("ITfThreadMgr.QueryInterface(ITfCompartmentMgr)", _call(self._thread_manager, 0, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p)), ctypes.byref(_IID_COMPARTMENT_MANAGER), ctypes.byref(self._compartment_manager))):
                return
            if not self._succeeded("ITfCompartmentMgr.GetCompartment", _call(self._compartment_manager, 3, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p)), ctypes.byref(_GUID_CONVERSION), ctypes.byref(self._compartment))):
                return
            if not self._succeeded("ITfCompartment.QueryInterface(ITfSource)", _call(self._compartment, 0, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p)), ctypes.byref(_IID_SOURCE), ctypes.byref(self._source))):
                return
            if not self._succeeded("ITfSource.AdviseSink", _call(self._source, 3, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_Guid), ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)), ctypes.byref(_IID_COMPARTMENT_EVENT_SINK), self._sink.pointer, ctypes.byref(self._cookie))):
                return
            self._active = True
            logger.debug("input_mode: subscribed cookie=%d", self._cookie.value)
        except OSError:
            logger.debug("input_mode: TSF initialization raised", exc_info=True)

    @staticmethod
    def _succeeded(stage: str, hr: int) -> bool:
        logger.debug("input_mode: %s hr=0x%08X", stage, hr & 0xFFFFFFFF)
        return hr >= 0

    def _emit_current(self) -> None:
        logger.debug("input_mode: ITfCompartmentEventSink.OnChange")
        self.changed.emit(self.current())
