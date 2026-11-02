"""原生文件 / 文件夹选择对话框（Web「新增工具 → 浏览路径」按钮用）。

bridge 与用户本机同机运行：Web 端发起一条 WS 命令，由 bridge 在用户屏幕上弹出
Windows 原生文件管理器对话框（comdlg32 打开文件 / shell32 文件夹浏览，
ctypes 直调，无 tkinter/PyQt 依赖），返回所选路径。

- 模态对话框阻塞调用线程 → handler 里用 asyncio.to_thread 跑（不卡事件循环）
- 取消选择 → 返回 ""（前端保持输入框原值）
- 非 Windows 系统 → DialogError DIALOG_UNSUPPORTED
"""
import ctypes
import platform
from ctypes import wintypes

_MAX_PATH = 32768


class DialogError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _fileopenfilename_struct():
    """FILEOPENFILENAMEW 的 ctypes 布局。

    注意：64 位版比 32 位版多出 6 个尾随 ULONG（__reserved1..6），
    且 文件偏移/索引 联合按 DWORD 对齐——少声明会让 lStructSize 对不上，
    GetOpenFileNameW 直接返回 FALSE（对话框不弹，静默失败）。
    lStructSize 一律填 ctypes.sizeof（本平台实测 64 位 = 152，API 已验证可弹出）。
    """
    is64 = ctypes.sizeof(ctypes.c_size_t) == 8
    _fields_ = [
        ("lStructSize", wintypes.UINT),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HANDLE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPCWSTR),
        ("nMaxCustFilter", wintypes.UINT),
        ("nFileIndex", wintypes.UINT),
        ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.UINT),
        ("lpstrFileTitle", wintypes.LPCWSTR),
        ("nMaxFileTitle", wintypes.UINT),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("dwFlags", wintypes.UINT),
        # 联合（nFileOffset/nFileIndex 与 AsUInt 共址）：按 4 字节对齐
        ("nFileOffsetAsUInt", wintypes.UINT),
        ("nFileIndexAsUInt", wintypes.UINT),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", wintypes.DWORD),
    ]
    if is64:
        _fields_ += [(f"__reserved{i}", wintypes.UINT) for i in range(1, 7)]
    return type("FILEOPENFILENAMEW", (ctypes.Structure,), {"_fields_": _fields_})


def pick_file(title: str = "选择工具路径", initial_dir: str = "") -> str:
    """打开「打开文件」对话框（comdlg32），返回所选文件路径；取消返回 ""。"""
    if not _is_windows():
        raise DialogError("DIALOG_UNSUPPORTED", "文件选择对话框仅支持 Windows 系统")
    comdlg32 = ctypes.windll.comdlg32
    kernel32 = ctypes.windll.kernel32
    FILEOPENFILENAMEW = _fileopenfilename_struct()

    # 64 位下必须显式声明 argtypes/restype（默认按 C int 传参会把指针截断为 32 位）
    comdlg32.GetOpenFileNameW.argtypes = [ctypes.POINTER(FILEOPENFILENAMEW)]
    comdlg32.GetOpenFileNameW.restype = wintypes.BOOL
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HANDLE

    buf = ctypes.create_unicode_buffer(_MAX_PATH)
    f = FILEOPENFILENAMEW()
    f.lStructSize = ctypes.sizeof(FILEOPENFILENAMEW)
    # LPWSTR 字段存数组需显式 cast（c_wchar_Array_N 与 c_wchar_p 不隐式兼容）
    f.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    f.nMaxFile = _MAX_PATH
    f.lpstrInitialDir = initial_dir or None
    f.lpstrTitle = title or "选择工具路径"
    f.hInstance = kernel32.GetModuleHandleW(None)  # 0 在个别系统上会导致对话框句柄异常
    # OFN_PATHMUSTEXIST | OFN_FILEMUSTEXIST | OFN_NOCHANGEDIR
    f.dwFlags = 0x00000800 | 0x00001000 | 0x08000000
    ok = comdlg32.GetOpenFileNameW(ctypes.byref(f))
    return buf.value if ok else ""


def pick_folder(title: str = "选择工具文件夹", _initial_dir: str = "") -> str:
    """打开文件夹浏览对话框（SHBrowseForFolder），返回所选文件夹路径；取消返回 ""。"""
    if not _is_windows():
        raise DialogError("DIALOG_UNSUPPORTED", "文件夹选择对话框仅支持 Windows 系统")
    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32

    class BROWSEINFOW(ctypes.Structure):
        _fields_ = [
            ("hwndOwner", wintypes.HWND),
            ("pidlRoot", ctypes.c_void_p),
            ("pszTitle", wintypes.LPCWSTR),
            ("lFlags", wintypes.UINT),
            ("lpCallback", ctypes.c_void_p),
            ("lParam", ctypes.c_ssize_t),
            ("ulResult", wintypes.UINT),
            ("iImage", ctypes.c_int),
        ]

    # 64 位下显式声明：SHBrowseForFolderW 返回 PIDL 指针（默认按 C int 会截断）
    assert ctypes.sizeof(BROWSEINFOW) in (48, 56), \
        f"BROWSEINFOW 尺寸异常：{ctypes.sizeof(BROWSEINFOW)}"
    shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BROWSEINFOW)]
    shell32.SHBrowseForFolderW.restype = ctypes.c_void_p
    shell32.SHGetPathFromIDListW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR]
    shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

    BIF_RETURNONLYFSDIRS = 0x0001  # 仅可返回磁盘目录
    bi = BROWSEINFOW()
    bi.pszTitle = title or "选择工具文件夹"
    bi.lFlags = BIF_RETURNONLYFSDIRS
    pidl = shell32.SHBrowseForFolderW(ctypes.byref(bi))
    if not pidl:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(_MAX_PATH)
        ok = shell32.SHGetPathFromIDListW(pidl, ctypes.cast(buf, wintypes.LPWSTR))
        return buf.value if ok else ""
    finally:
        ole32.CoTaskMemFree(pidl)
