"""UI Automation (UIA) 客户端的极简 ctypes/COM 封装。

不引入 comtypes/uiautomation 等第三方库，只用 Windows 自带的
``UIAutomationCore`` COM 接口：
* ``IUIAutomation::ElementFromHandle``
* ``IUIAutomation::CreatePropertyCondition`` + ``FindAll``
* ``IUIAutomationElement`` 的 Current 属性
* ``IUIAutomationValuePattern``（仅读非密码控件，且仅用于诊断/校验）

本模块只读取控件的可访问性属性（名称、类型、矩形、是否密码框、是否启用），
**绝不**读取其它进程内存，也**绝不**读取密码框的值。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
import uuid
from dataclasses import dataclass
from typing import Iterable, Iterator

LOGGER = logging.getLogger("login_assistant.core.uia")

CLSID_CUIAutomation = "FF48DBA4-60EF-4201-AA87-54103EEF594E"
IID_IUIAutomation = "30CBE57D-D9D0-452A-AB13-7AC5AC4825EE"
IID_IUIAutomationElement = "D22108AA-8AC5-49A5-837B-37BBB3D7591E"
IID_IUIAutomationElementArray = "14314595-B4BC-4055-95F2-58F2E42C9855"
IID_IUIAutomationValuePattern = "A94CD8B1-0844-4CD6-9D2D-640537AB39E9"

CLSCTX_INPROC_SERVER = 1
COINIT_MULTITHREADED = 0
RPC_E_CHANGED_MODE = 0x80010106

TreeScope_Descendants = 4

UIA_ControlTypePropertyId = 30003
UIA_ValuePatternId = 10002

UIA_EditControlTypeId = 50004
UIA_ButtonControlTypeId = 50000
UIA_TextControlTypeId = 50020

S_OK = 0
S_FALSE = 1

_ole32 = ctypes.WinDLL("ole32", use_last_error=True)
_oleaut32 = ctypes.WinDLL("oleaut32", use_last_error=True)


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value: str) -> "GUID":
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class _VARIANT_VALUE(ctypes.Union):
    _fields_ = [
        ("llVal", ctypes.c_longlong),
        ("lVal", ctypes.c_long),
        ("dblVal", ctypes.c_double),
        ("pdispVal", ctypes.c_void_p),
        ("pbstrVal", ctypes.c_void_p),
        ("parray", ctypes.c_void_p),
        ("padding", ctypes.c_byte * (16 if ctypes.sizeof(ctypes.c_void_p) == 8 else 8)),
    ]


class VARIANT(ctypes.Structure):
    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("value", _VARIANT_VALUE),
    ]


VT_I4 = 3
VT_R8 = 5
VT_BSTR = 8
VT_BOOL = 11
VT_ARRAY = 0x2000

UIA_ProcessIdPropertyId = 30002
UIA_BoundingRectanglePropertyId = 30001
UIA_NamePropertyId = 30005
UIA_HasKeyboardFocusPropertyId = 30008
UIA_IsEnabledPropertyId = 30010
UIA_AutomationIdPropertyId = 30011
UIA_ClassNamePropertyId = 30012
UIA_IsPasswordPropertyId = 30019
UIA_NativeWindowHandlePropertyId = 30020
UIA_IsOffscreenPropertyId = 30022


class UiaError(RuntimeError):
    def __init__(self, message: str, hresult: int | None = None) -> None:
        super().__init__(message)
        self.hresult = hresult


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    @property
    def valid(self) -> bool:
        return self.width > 2 and self.height > 2

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


@dataclass(frozen=True)
class ElementInfo:
    control_type: int
    name: str
    automation_id: str
    class_name: str
    rect: Rect | None
    is_password: bool
    is_enabled: bool
    is_offscreen: bool
    process_id: int
    has_keyboard_focus: bool
    native_window_handle: int = 0

    @property
    def center(self) -> tuple[int, int] | None:
        return self.rect.center if self.rect and self.rect.valid else None


_ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_ole32.CoInitializeEx.restype = ctypes.c_long
_ole32.CoUninitialize.argtypes = []
_ole32.CoUninitialize.restype = None
_ole32.CoCreateInstance.argtypes = [
    ctypes.POINTER(GUID),
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(GUID),
    ctypes.POINTER(ctypes.c_void_p),
]
_ole32.CoCreateInstance.restype = ctypes.c_long
_oleaut32.SysFreeString.argtypes = [ctypes.c_void_p]
_oleaut32.SysFreeString.restype = None
_oleaut32.VariantClear.argtypes = [ctypes.POINTER(VARIANT)]
_oleaut32.VariantClear.restype = ctypes.c_long
_oleaut32.SafeArrayGetLBound.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_long)]
_oleaut32.SafeArrayGetLBound.restype = ctypes.c_long
_oleaut32.SafeArrayGetUBound.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_long)]
_oleaut32.SafeArrayGetUBound.restype = ctypes.c_long
_oleaut32.SafeArrayGetElement.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_long), ctypes.c_void_p]
_oleaut32.SafeArrayGetElement.restype = ctypes.c_long


def _vtbl(ptr: int) -> ctypes.POINTER(ctypes.c_void_p):
    return ctypes.cast(ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents


def _call(ptr: int, index: int, restype, argtypes, *args):  # type: ignore[no-untyped-def]
    if not ptr:
        raise UiaError("空 COM 指针")
    address = _vtbl(ptr)[index]
    if not address:
        raise UiaError("COM vtable 槽位为空")
    prototype = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return prototype(address)(ptr, *args)


def _hr_failed(hr: int) -> bool:
    return int(hr) < 0


def _bstr_to_str(ptr: int | None) -> str:
    if not ptr:
        return ""
    try:
        return ctypes.wstring_at(ptr)
    finally:
        _oleaut32.SysFreeString(ptr)


class Element:
    """IUIAutomationElement 的轻量包装；由 UiaSession 统一释放。"""

    def __init__(self, ptr: int, session: "UiaSession") -> None:
        self.ptr = int(ptr)
        self._session = session
        self._released = False
        self._info: ElementInfo | None = None

    # -- properties --------------------------------------------------------
    # 注意：不同 Windows SDK 版本的 IUIAutomationElement vtable 在 20 号之后
    # 存在差异，直接按序号调用 Current 方法容易错位（实测 IsPassword /
    # IsOffscreen / BoundingRectangle 会读错）。这里统一改用
    # GetCurrentPropertyValue(propertyId) + VARIANT，稳定且可移植。
    def _variant(self, property_id: int) -> VARIANT | None:
        variant = VARIANT()
        hr = _call(
            self.ptr,
            10,
            ctypes.c_long,
            [ctypes.c_int, ctypes.POINTER(VARIANT)],
            property_id,
            ctypes.byref(variant),
        )
        if _hr_failed(hr):
            return None
        return variant

    @staticmethod
    def _clear_variant(variant: VARIANT | None) -> None:
        if variant is None:
            return
        try:
            _oleaut32.VariantClear(ctypes.byref(variant))
        except Exception:
            pass

    def _property_int(self, property_id: int) -> int:
        variant = self._variant(property_id)
        if variant is None:
            return 0
        try:
            if variant.vt == VT_I4:
                return int(variant.value.lVal)
            return 0
        finally:
            self._clear_variant(variant)

    def _property_bool(self, property_id: int) -> bool:
        variant = self._variant(property_id)
        if variant is None:
            return False
        try:
            if variant.vt == VT_BOOL:
                return bool(variant.value.lVal & 0xFFFF)
            return False
        finally:
            self._clear_variant(variant)

    def _property_bstr(self, property_id: int) -> str:
        variant = self._variant(property_id)
        if variant is None:
            return ""
        try:
            if variant.vt != VT_BSTR or not variant.value.pbstrVal:
                return ""
            return ctypes.wstring_at(variant.value.pbstrVal)
        finally:
            self._clear_variant(variant)

    def _property_rect(self, property_id: int) -> Rect | None:
        variant = self._variant(property_id)
        if variant is None:
            return None
        try:
            if not (variant.vt & VT_ARRAY) or (variant.vt & 0x0FFF) != VT_R8:
                return None
            psa = variant.value.parray
            if not psa:
                return None
            lower = ctypes.c_long(0)
            upper = ctypes.c_long(0)
            if _hr_failed(_oleaut32.SafeArrayGetLBound(psa, 1, ctypes.byref(lower))):
                return None
            if _hr_failed(_oleaut32.SafeArrayGetUBound(psa, 1, ctypes.byref(upper))):
                return None
            if upper.value - lower.value + 1 < 4:
                return None
            values: list[float] = []
            for offset in range(4):
                index = ctypes.c_long(lower.value + offset)
                value = ctypes.c_double(0.0)
                if _hr_failed(
                    _oleaut32.SafeArrayGetElement(psa, ctypes.byref(index), ctypes.byref(value))
                ):
                    return None
                values.append(value.value)
            left, top, width, height = (int(round(item)) for item in values)
            if width <= 0 or height <= 0:
                return None
            return Rect(left, top, left + width, top + height)
        finally:
            self._clear_variant(variant)

    @property
    def control_type(self) -> int:
        return self._property_int(UIA_ControlTypePropertyId)

    @property
    def name(self) -> str:
        return self._property_bstr(UIA_NamePropertyId)

    @property
    def automation_id(self) -> str:
        return self._property_bstr(UIA_AutomationIdPropertyId)

    @property
    def class_name(self) -> str:
        return self._property_bstr(UIA_ClassNamePropertyId)

    @property
    def process_id(self) -> int:
        return self._property_int(UIA_ProcessIdPropertyId)

    @property
    def is_enabled(self) -> bool:
        return self._property_bool(UIA_IsEnabledPropertyId)

    @property
    def is_offscreen(self) -> bool:
        return self._property_bool(UIA_IsOffscreenPropertyId)

    @property
    def is_password(self) -> bool:
        return self._property_bool(UIA_IsPasswordPropertyId)

    @property
    def has_keyboard_focus(self) -> bool:
        return self._property_bool(UIA_HasKeyboardFocusPropertyId)

    @property
    def native_window_handle(self) -> int:
        return self._property_int(UIA_NativeWindowHandlePropertyId)

    @property
    def rect(self) -> Rect | None:
        return self._property_rect(UIA_BoundingRectanglePropertyId)

    def info(self) -> ElementInfo:
        if self._info is None:
            self._info = ElementInfo(
                control_type=self.control_type,
                name=self.name,
                automation_id=self.automation_id,
                class_name=self.class_name,
                rect=self.rect,
                is_password=self.is_password,
                is_enabled=self.is_enabled,
                is_offscreen=self.is_offscreen,
                process_id=self.process_id,
                has_keyboard_focus=self.has_keyboard_focus,
                native_window_handle=self.native_window_handle,
            )
        return self._info

    # -- actions -----------------------------------------------------------
    def set_focus(self) -> bool:
        hr = _call(self.ptr, 3, ctypes.c_long, [])
        return not _hr_failed(hr)

    def value(self) -> str | None:
        """读取 ValuePattern 的当前值；密码框返回 None 且绝不调用。"""
        if self.is_password:
            return None
        pattern = ctypes.c_void_p()
        hr = _call(
            self.ptr,
            16,
            ctypes.c_long,
            [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)],
            UIA_ValuePatternId,
            ctypes.byref(pattern),
        )
        if _hr_failed(hr) or not pattern.value:
            return None
        try:
            out = ctypes.c_void_p()
            hr = _call(
                pattern.value,
                4,
                ctypes.c_long,
                [ctypes.POINTER(ctypes.c_void_p)],
                ctypes.byref(out),
            )
            if _hr_failed(hr):
                return None
            return _bstr_to_str(out.value)
        finally:
            _call(pattern.value, 2, ctypes.c_ulong, [])

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        if self.ptr:
            try:
                _call(self.ptr, 2, ctypes.c_ulong, [])
            except Exception:
                pass
            self.ptr = 0

    def __del__(self) -> None:
        try:
            self.release()
        except Exception:
            pass


class UiaSession:
    """每个线程一个实例；必须在该线程内 close。"""

    def __init__(self) -> None:
        self._automation = 0
        self._initialized = False
        self._elements: list[Element] = []
        self._closed = False

    def __enter__(self) -> "UiaSession":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

    def open(self) -> None:
        hr = _ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
        if _hr_failed(hr) and (int(hr) & 0xFFFFFFFF) != RPC_E_CHANGED_MODE:
            raise UiaError(f"CoInitializeEx 失败 (HRESULT=0x{int(hr) & 0xFFFFFFFF:08X})", int(hr))
        self._initialized = not _hr_failed(hr)
        clsid = GUID.from_string(CLSID_CUIAutomation)
        iid = GUID.from_string(IID_IUIAutomation)
        automation = ctypes.c_void_p()
        hr = _ole32.CoCreateInstance(
            ctypes.byref(clsid),
            None,
            CLSCTX_INPROC_SERVER,
            ctypes.byref(iid),
            ctypes.byref(automation),
        )
        if _hr_failed(hr) or not automation.value:
            if self._initialized:
                _ole32.CoUninitialize()
                self._initialized = False
            raise UiaError(f"无法创建 UIAutomation 对象 (HRESULT=0x{int(hr) & 0xFFFFFFFF:08X})", int(hr))
        self._automation = int(automation.value)
        LOGGER.debug("UIAutomation 初始化完成")

    # -- factory -----------------------------------------------------------
    def _track(self, ptr: int) -> Element:
        element = Element(ptr, self)
        self._elements.append(element)
        return element

    def element_from_handle(self, hwnd: int) -> Element | None:
        out = ctypes.c_void_p()
        hr = _call(
            self._automation,
            6,
            ctypes.c_long,
            [wintypes.HWND, ctypes.POINTER(ctypes.c_void_p)],
            hwnd,
            ctypes.byref(out),
        )
        if _hr_failed(hr) or not out.value:
            return None
        return self._track(int(out.value))

    def element_from_point(self, x: int, y: int) -> Element | None:
        """返回屏幕物理坐标下最上层的 UIA 元素（只读；不点击）。"""
        point = wintypes.POINT(int(x), int(y))
        out = ctypes.c_void_p()
        hr = _call(
            self._automation,
            7,  # IUIAutomation::ElementFromPoint
            ctypes.c_long,
            [wintypes.POINT, ctypes.POINTER(ctypes.c_void_p)],
            point,
            ctypes.byref(out),
        )
        if _hr_failed(hr) or not out.value:
            return None
        return self._track(int(out.value))

    def _condition_for_control_type(self, control_type: int) -> int:
        variant = VARIANT()
        variant.vt = VT_I4
        variant.value.lVal = int(control_type)
        condition = ctypes.c_void_p()
        hr = _call(
            self._automation,
            23,
            ctypes.c_long,
            [ctypes.c_int, VARIANT, ctypes.POINTER(ctypes.c_void_p)],
            UIA_ControlTypePropertyId,
            variant,
            ctypes.byref(condition),
        )
        if _hr_failed(hr) or not condition.value:
            raise UiaError(f"CreatePropertyCondition 失败 (HRESULT=0x{int(hr) & 0xFFFFFFFF:08X})", int(hr))
        return int(condition.value)

    def find_all(self, parent: Element, control_type: int) -> list[Element]:
        condition = self._condition_for_control_type(control_type)
        array = ctypes.c_void_p()
        try:
            hr = _call(
                parent.ptr,
                6,
                ctypes.c_long,
                [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)],
                TreeScope_Descendants,
                condition,
                ctypes.byref(array),
            )
            if _hr_failed(hr):
                return []
            if not array.value:
                return []
            length = ctypes.c_int(0)
            hr = _call(
                array.value,
                3,
                ctypes.c_long,
                [ctypes.POINTER(ctypes.c_int)],
                ctypes.byref(length),
            )
            if _hr_failed(hr):
                return []
            result: list[Element] = []
            for index in range(int(length.value)):
                child = ctypes.c_void_p()
                hr = _call(
                    array.value,
                    4,
                    ctypes.c_long,
                    [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)],
                    index,
                    ctypes.byref(child),
                )
                if not _hr_failed(hr) and child.value:
                    result.append(self._track(int(child.value)))
            return result
        finally:
            if array.value:
                _call(array.value, 2, ctypes.c_ulong, [])
            _call(condition, 2, ctypes.c_ulong, [])

    # -- convenience -------------------------------------------------------
    def edits(self, hwnd: int) -> list[Element]:
        root = self.element_from_handle(hwnd)
        if root is None:
            return []
        return [
            element
            for element in self.find_all(root, UIA_EditControlTypeId)
            if not element.is_offscreen
        ]

    def buttons(self, hwnd: int) -> list[Element]:
        root = self.element_from_handle(hwnd)
        if root is None:
            return []
        return [
            element
            for element in self.find_all(root, UIA_ButtonControlTypeId)
            if not element.is_offscreen
        ]

    def texts(self, hwnd: int, limit: int = 200) -> list[str]:
        root = self.element_from_handle(hwnd)
        if root is None:
            return []
        result: list[str] = []
        for element in self.find_all(root, UIA_TextControlTypeId):
            if len(result) >= limit:
                break
            if element.is_offscreen:
                continue
            name = element.name.strip()
            if name and len(name) <= 300:
                result.append(name)
        return result

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for element in reversed(self._elements):
            try:
                element.release()
            except Exception:
                pass
        self._elements.clear()
        if self._automation:
            try:
                _call(self._automation, 2, ctypes.c_ulong, [])
            except Exception:
                pass
            self._automation = 0
        if self._initialized:
            try:
                _ole32.CoUninitialize()
            except Exception:
                pass
            self._initialized = False


def probe(hwnd: int) -> dict[str, object]:
    """诊断用：返回目标窗口的控件摘要（不含任何输入值）。"""
    with UiaSession() as session:
        root = session.element_from_handle(hwnd)
        if root is None:
            return {"ok": False, "error": "无法取得窗口的 UIA 根元素"}
        edits = session.find_all(root, UIA_EditControlTypeId)
        buttons = session.find_all(root, UIA_ButtonControlTypeId)
        texts = session.find_all(root, UIA_TextControlTypeId)
        return {
            "ok": True,
            "edits": [element.info() for element in edits[:20]],
            "buttons": [element.info() for element in buttons[:20]],
            "texts": [text.name.strip() for text in texts[:40] if text.name.strip()],
        }
