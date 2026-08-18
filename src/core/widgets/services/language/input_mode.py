import ctypes
import uuid
from ctypes import wintypes

from PyQt6.QtCore import QObject, pyqtSignal

from core.widgets.services.language.mode import callback_address, input_mode_key


_S_OK = 0
_VT_I4 = 3
_VT_UI4 = 19


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
            return "unknown"
        value = _Variant()
        hr = _call(self._compartment, 4, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_Variant)), ctypes.byref(value))
        if hr < 0 or value.vt not in (_VT_I4, _VT_UI4):
            return "unknown"
        return input_mode_key(value.value.ulVal)

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
        create = ctypes.WinDLL("msctf").TF_CreateThreadMgr
        create.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        create.restype = ctypes.c_long
        if create(ctypes.byref(self._thread_manager)) < 0:
            return
        client_id = wintypes.DWORD()
        if _call(self._thread_manager, 3, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)), ctypes.byref(client_id)) < 0:
            return
        if _call(self._thread_manager, 13, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)), ctypes.byref(self._compartment_manager)) < 0:
            return
        if _call(self._compartment_manager, 3, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p)), ctypes.byref(_GUID_CONVERSION), ctypes.byref(self._compartment)) < 0:
            return
        if _call(self._compartment, 0, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_Guid), ctypes.POINTER(ctypes.c_void_p)), ctypes.byref(_IID_SOURCE), ctypes.byref(self._source)) < 0:
            return
        if _call(self._source, 3, ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_Guid), ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)), ctypes.byref(_IID_COMPARTMENT_EVENT_SINK), self._sink.pointer, ctypes.byref(self._cookie)) < 0:
            return
        self._active = True

    def _emit_current(self) -> None:
        self.changed.emit(self.current())
