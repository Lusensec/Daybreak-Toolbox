"""bridge.native_browser —— 参数校验与无窗口场景的错误码（不涉及实际 WebView2）。"""
import pytest

from bridge import native_browser as nb


def test_available_returns_bool():
    assert isinstance(nb.available(), bool)


def test_norm_rect_valid():
    assert nb._norm_rect({"x": 10, "y": 20, "width": 300, "height": 200}) == (
        10.0,
        20.0,
        300.0,
        200.0,
    )


@pytest.mark.parametrize("rect", [{}, {"width": 0, "height": 10}, {"width": 10, "height": 0}])
def test_norm_rect_invalid(rect):
    with pytest.raises(nb.NativeBrowserError) as e:
        nb._norm_rect(rect)
    assert e.value.code == "BROWSER_BAD_RECT"


def test_attach_requires_tab_and_url():
    with pytest.raises(nb.NativeBrowserError) as e:
        nb.attach("", "https://example.com", {"width": 100, "height": 100})
    assert e.value.code == "BROWSER_BAD_TAB"

    with pytest.raises(nb.NativeBrowserError) as e2:
        nb.attach("t1", "", {"width": 100, "height": 100})
    assert e2.value.code == "BROWSER_BAD_URL"


def test_attach_without_window_raises():
    """测试进程没有 pywebview 主窗口：Windows 上是 NO_WINDOW，其它平台是 UNSUPPORTED。"""
    with pytest.raises(nb.NativeBrowserError) as e:
        nb.attach("t1", "https://example.com", {"x": 0, "y": 0, "width": 100, "height": 100})
    assert e.value.code in ("BROWSER_NO_WINDOW", "BROWSER_UNSUPPORTED")
