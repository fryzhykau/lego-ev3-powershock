"""Read a DualShock 4's battery, model and firmware straight from Windows (no browser picker).

Browsers only give a page HID access after the user picks the device in a browser dialog,
and some browsers (embedded ones) never show that dialog. The console server runs on the
same laptop, so it can open the controller through Windows' own HID API instead.

Uses only ctypes (hid.dll / setupapi.dll); nothing to install. Windows only.

    python pc/ds4_hid.py      # prints what it finds
"""
import ctypes
import ctypes.wintypes as wt
import json
import sys
import threading

SONY = 0x054C
MODELS = {
    0x05C4: "DualShock 4, first version (CUH-ZCT1)",
    0x09CC: "DualShock 4, second version (CUH-ZCT2)",
    0x0BA0: "Sony wireless adapter for DualShock 4",
}

if sys.platform == "win32":
    hid = ctypes.WinDLL("hid")
    setupapi = ctypes.WinDLL("setupapi")
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]

    class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID), ("Flags", wt.DWORD), ("Reserved", ctypes.c_void_p)]

    class HIDD_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Size", wt.ULONG), ("VendorID", wt.USHORT), ("ProductID", wt.USHORT), ("VersionNumber", wt.USHORT)]

    class HIDP_CAPS(ctypes.Structure):
        _fields_ = [("Usage", wt.USHORT), ("UsagePage", wt.USHORT), ("InputReportByteLength", wt.USHORT),
                    ("OutputReportByteLength", wt.USHORT), ("FeatureReportByteLength", wt.USHORT),
                    ("Reserved", wt.USHORT * 17), ("rest", wt.USHORT * 10)]

    setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
    setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD]
    setupapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID), wt.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
    setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
    k32.CreateFileW.restype = wt.HANDLE
    k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
    k32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
    k32.CloseHandle.argtypes = [wt.HANDLE]
    k32.CancelIoEx.argtypes = [wt.HANDLE, ctypes.c_void_p]
    hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
    hid.HidD_GetAttributes.argtypes = [wt.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
    hid.HidD_GetPreparsedData.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
    hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
    hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
    hid.HidD_GetFeature.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]

INVALID = ctypes.c_void_p(-1).value


def _paths():
    """Device paths of every Sony HID interface Windows has right now."""
    g = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(g))
    info = setupapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None, 0x12)  # PRESENT | DEVICEINTERFACE
    out, i = [], 0
    try:
        while True:
            d = SP_DEVICE_INTERFACE_DATA(); d.cbSize = ctypes.sizeof(d)
            if not setupapi.SetupDiEnumDeviceInterfaces(info, None, ctypes.byref(g), i, ctypes.byref(d)):
                break
            i += 1
            need = wt.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(d), None, 0, ctypes.byref(need), None)
            buf = ctypes.create_string_buffer(need.value)
            ctypes.c_uint32.from_buffer(buf).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6  # cbSize
            if setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(d), buf, need, None, None):
                path = ctypes.wstring_at(ctypes.addressof(buf) + 4)
                low = path.lower()
                if "vid_054c" in low or "vid&0002054c" in low:
                    out.append(path)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(info)
    return out


def _read_report(h, size, timeout=1.5):
    """One input report, or None if none arrives in time (ReadFile blocks, so it runs in a thread)."""
    buf, got, n = ctypes.create_string_buffer(size), [None], wt.DWORD()

    def run():
        if k32.ReadFile(h, buf, size, ctypes.byref(n), None):
            got[0] = buf.raw[:n.value]
    t = threading.Thread(target=run, daemon=True)
    t.start(); t.join(timeout)
    if t.is_alive():
        k32.CancelIoEx(h, None); t.join(0.5)
    return got[0]


def _feature(h, rid, size):
    buf = ctypes.create_string_buffer(size)
    buf[0] = rid
    return buf.raw if hid.HidD_GetFeature(h, buf, size) else None


def read():
    """{'ok': True, model, pid, link, level, cable, charging, percent, fw: {...}} or {'ok': False, 'error': ...}."""
    if sys.platform != "win32":
        return {"ok": False, "error": "Reading the controller directly only works on Windows."}
    paths = _paths()
    if not paths:
        return {"ok": False, "error": "Windows doesn't have a Sony controller connected right now."}
    last = "Couldn't open the controller."
    for path in paths:
        h = k32.CreateFileW(path, 0xC0000000, 3, None, 3, 0, None)  # read+write, shared, open existing
        if h in (None, INVALID):
            last = "Windows wouldn't let this program open the controller."
            continue
        try:
            a = HIDD_ATTRIBUTES(); a.Size = ctypes.sizeof(a)
            hid.HidD_GetAttributes(h, ctypes.byref(a))
            pre, caps = ctypes.c_void_p(), HIDP_CAPS()
            hid.HidD_GetPreparsedData(h, ctypes.byref(pre)); hid.HidP_GetCaps(pre, ctypes.byref(caps)); hid.HidD_FreePreparsedData(pre)
            if caps.UsagePage != 1 or caps.Usage not in (4, 5):  # only the gamepad interface
                continue
            bt = "00001124" in path
            res = {"ok": True, "pid": a.ProductID, "model": MODELS.get(a.ProductID, "Sony controller"), "link": "Bluetooth" if bt else "USB cable"}
            # Over Bluetooth the full report (with the battery) only starts after the calibration feature is read.
            if caps.FeatureReportByteLength:
                _feature(h, 0x02, caps.FeatureReportByteLength)
                f = _feature(h, 0xA3, caps.FeatureReportByteLength)
                if f:
                    txt = lambda s: s.split(b"\0")[0].decode("ascii", "replace").strip()
                    u16 = lambda o: f[o] | (f[o + 1] << 8)
                    res["fw"] = {"date": txt(f[1:17]), "time": txt(f[17:33]), "hw": u16(35), "fw": u16(41)}
            b = None
            for _ in range(20):
                r = _read_report(h, caps.InputReportByteLength)
                if not r:
                    break
                if r[0] == 0x01 and len(r) > 30 and not bt:
                    b = r[30]
                elif r[0] == 0x11 and len(r) > 32:
                    b = r[32]
                if b is not None:
                    break
            if b is not None:
                cable, level = bool(b & 0x10), b & 0x0F
                res.update(cable=cable, level=level, charging=cable and level < 11,
                           percent=min(100, round(level / (11 if cable else 10) * 100)))
            else:
                res["batteryError"] = "The controller didn't send its battery level."
            return res
        finally:
            k32.CloseHandle(h)
    return {"ok": False, "error": last}


if __name__ == "__main__":
    print(json.dumps(read(), indent=2))
