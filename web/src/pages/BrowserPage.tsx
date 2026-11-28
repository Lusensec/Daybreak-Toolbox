import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ExternalLink, RefreshCw } from "lucide-react";
import { sendCommand } from "../services/ws";
import { useBrowserStore } from "../features/browser/store";
import { useSettingsModal } from "../store/settingsModal";
import { usePromptStore } from "../components/PromptDialog";
import { useToast } from "../components/toast";
import "./BrowserPage.css";

/** 地址栏输入归一化：补协议、兼容 // 与 localhost；已有协议原样保留 */
function normalizeUrl(raw: string): string {
  const s = raw.trim();
  if (!s) return "";
  if (/^(https?|file|about|data|mailto|ftp):/i.test(s)) return s;
  if (s.startsWith("//")) return `https:${s}`;
  // 本地调试地址默认 http，其它默认 https
  if (/^(localhost|127\.0\.0\.1|\[::1\])(:\d+)?(\/|$)/i.test(s)) return `http://${s}`;
  return `https://${s}`;
}

/**
 * 内置浏览器页（/browser/:menu/:name）：
 *  - 标签数据来自 useBrowserStore（launch.ts 打开「链接打开」类工具时写入）
 *  - v2.3.0：Windows 窗口模式下优先用**原生 WebView2 子窗体**承载（顶层文档，不受
 *    目标站点 X-Frame-Options 限制）；拿到 `app.env.native_browser=false` 或原生创建
 *    失败时，回退到 iframe（原实现，保留给服务模式/非 Windows/异常场景）。
 *  - iframe 模式：全部标签常驻挂载（仅 display 切换），切标签不丢状态。
 *  - 原生模式：页面区域只画一个空占位，位置/尺寸通过 ResizeObserver 同步给 Python。
 */
export function BrowserPage() {
  // react-router 已对路由参数解码；无值时退化为空串（最终落到「标签不存在」空状态）
  const { menu = "", name = "" } = useParams<{ menu: string; name: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const tabs = useBrowserStore((s) => s.tabs);
  const settingsOpen = useSettingsModal((s) => s.open);
  const dialogOpen = usePromptStore((s) => s.resolve !== null);
  // 每个标签的刷新代数：只递增当前标签 → key 变化 → iframe 重新挂载
  const [nonces, setNonces] = useState<Record<string, number>>({});
  const [opening, setOpening] = useState(false);
  // unknown：还在询问 app.env；yes/no：是否具备原生嵌入条件
  const [nativeEnv, setNativeEnv] = useState<"unknown" | "yes" | "no">("unknown");
  const [nativeFailed, setNativeFailed] = useState(false);
  // 地址栏草稿：切换标签/页面 URL 变化时同步，回车提交后写回 store
  const [address, setAddress] = useState("");
  const frameRef = useRef<HTMLDivElement | null>(null);
  const knownTabsRef = useRef<string[]>([]);

  const activeTab = tabs.find((t) => t.menu === menu && t.name === name);
  const activeTabId = activeTab?.id ?? "";
  const nativeMode = nativeEnv === "yes" && !nativeFailed;

  // 路由即激活标签：从顶栏入口或直接改地址进入时，让 store.activeId 跟随路由
  useEffect(() => {
    if (activeTabId) useBrowserStore.getState().setActive(activeTabId);
  }, [activeTabId]);

  // 标签切换或 URL 被外部更新时，同步地址栏草稿
  useEffect(() => {
    setAddress(activeTab?.url ?? "");
  }, [activeTabId, activeTab?.url]);

  // 询问运行形态：只有窗口模式 + Windows 才尝试原生嵌入
  useEffect(() => {
    let alive = true;
    void sendCommand("app.env", {})
      .then((r) => {
        if (!alive) return;
        setNativeEnv(r.native_browser === true ? "yes" : "no");
      })
      .catch(() => {
        if (alive) setNativeEnv("no");
      });
    return () => {
      alive = false;
    };
  }, []);

  const readRect = useCallback(() => {
    const el = frameRef.current;
    if (!el) return null;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return null;
    return { x: r.left, y: r.top, width: r.width, height: r.height };
  }, []);

  // 激活/新建原生标签：后端会隐藏其它标签，并复用已存在的宿主（保留页面状态）
  useEffect(() => {
    if (!nativeMode || !activeTab) return;
    const rect = readRect();
    if (!rect) return;
    let cancelled = false;
    void sendCommand("browser.attach", {
      tab_id: activeTab.id,
      url: activeTab.url,
      rect,
      show: true,
    }).catch((e) => {
      if (cancelled) return;
      setNativeFailed(true);
      toast.err(`原生浏览器不可用，已回退 iframe：${e instanceof Error ? e.message : String(e)}`);
    });
    return () => {
      cancelled = true;
    };
  }, [nativeMode, activeTab, readRect, toast]);

  // 窗口缩放/布局变化时同步原生控件矩形（CSS 像素；DPI 由后端换算）
  useEffect(() => {
    if (!nativeMode || !activeTab) return;
    const el = frameRef.current;
    if (!el) return;
    const sync = () => {
      const rect = readRect();
      if (rect) void sendCommand("browser.set_rect", { rect }).catch(() => {});
    };
    const ro = new ResizeObserver(sync);
    ro.observe(el);
    window.addEventListener("resize", sync);
    sync();
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", sync);
    };
  }, [nativeMode, activeTab, readRect]);

  // 设置弹窗/重命名弹窗是 HTML 层，原生控件会盖住它们 → 打开时隐藏浏览器，关闭后恢复
  useEffect(() => {
    if (!nativeMode || !activeTab) return;
    if (settingsOpen || dialogOpen) {
      void sendCommand("browser.hide", {}).catch(() => {});
    } else {
      void sendCommand("browser.activate", { tab_id: activeTab.id }).catch(() => {});
    }
  }, [nativeMode, settingsOpen, dialogOpen, activeTab]);

  // 标签被关闭时释放对应原生宿主（最后一个标签由页面卸载统一隐藏）
  useEffect(() => {
    if (!nativeMode) return;
    const current = new Set(tabs.map((t) => t.id));
    for (const id of knownTabsRef.current) {
      if (!current.has(id)) void sendCommand("browser.close", { tab_id: id }).catch(() => {});
    }
    knownTabsRef.current = [...current];
  }, [nativeMode, tabs]);

  // 离开浏览器页（切菜单/回首页）时隐藏原生控件，避免覆盖其它页面
  useEffect(() => {
    if (!nativeMode) return;
    return () => {
      void sendCommand("browser.hide", {}).catch(() => {});
    };
  }, [nativeMode]);

  /** 刷新当前标签：原生走 WebView2.Reload，iframe 走 nonce 重建 */
  function refresh() {
    if (!activeTab) return;
    if (nativeMode) {
      void sendCommand("browser.reload", { tab_id: activeTab.id }).catch((e) => {
        toast.err(`刷新失败：${e instanceof Error ? e.message : String(e)}`);
      });
      return;
    }
    setNonces((prev) => ({ ...prev, [activeTab.id]: (prev[activeTab.id] ?? 0) + 1 }));
  }

  /** 地址栏回车：更新标签 URL；原生模式由 attach 副作用导航，iframe 模式由 src 变化重载 */
  function submitAddress() {
    if (!activeTab) return;
    const url = normalizeUrl(address);
    if (!url) {
      setAddress(activeTab.url);
      return;
    }
    setAddress(url);
    useBrowserStore.getState().updateTabUrl(activeTab.id, url);
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
  }

  /** 在系统默认浏览器中打开（tool.run 会按「链接打开」方式交给本机处理） */
  async function openExternal() {
    if (!activeTab || opening) return;
    setOpening(true);
    try {
      const r = await sendCommand("tool.run", { menu: activeTab.menu, name: activeTab.name });
      toast.ok(String(r.message ?? "已在外部浏览器打开"));
    } catch (e) {
      // sendCommand 超时会抛 "cmd tool.run timeout"，与普通失败一样给出明确提示
      toast.err(`外部打开失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setOpening(false);
    }
  }

  if (!activeTab) {
    return (
      <div className="browser-page">
        <div className="browser-page__empty">
          <div className="browser-page__empty-title">标签不存在</div>
          <div className="browser-page__empty-hint">
            该链接工具未在本次会话中打开，或对应标签已被关闭。
          </div>
          <button onClick={() => navigate("/")}>返回首页</button>
        </div>
      </div>
    );
  }

  return (
    <div className="browser-page">
      <div className="browser-page__bar">
        <input
          className="browser-page__url"
          value={address}
          onChange={(e) => setAddress(e.target.value)}
          onFocus={(e) => e.currentTarget.select()}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submitAddress();
            } else if (e.key === "Escape") {
              setAddress(activeTab.url);
              e.currentTarget.blur();
            }
          }}
          spellCheck={false}
          autoComplete="off"
          placeholder="输入网址后按回车访问"
          title="输入网址后按回车访问"
        />
        <button className="browser-page__btn" onClick={refresh} title="重新加载当前页面">
          <RefreshCw size={14} />
          刷新
        </button>
        <button
          className="browser-page__btn"
          onClick={() => void openExternal()}
          disabled={opening}
          title="用系统默认浏览器打开该链接"
        >
          <ExternalLink size={14} />
          在外部浏览器打开
        </button>
      </div>

      <div className="browser-page__frames">
        {nativeMode ? (
          // 原生控件由 Python 覆盖在此矩形上；占位仅用于测量与兜底背景
          <div className="browser-page__native" ref={frameRef}>
            <span className="browser-page__native-hint">正在加载页面…</span>
          </div>
        ) : nativeEnv === "unknown" ? (
          <div className="browser-page__preparing">正在准备浏览器…</div>
        ) : (
          /* iframe 降级：全部标签常驻，非激活项 display:none，切回不重新加载 */
          tabs.map((tab) => (
            <div
              key={tab.id}
              className="browser-page__frame"
              style={{ display: tab.id === activeTab.id ? "block" : "none" }}
            >
              <iframe
                key={`${tab.id}:${nonces[tab.id] ?? 0}`}
                src={tab.url}
                title={tab.name}
                referrerPolicy="no-referrer"
              />
            </div>
          ))
        )}
      </div>
    </div>
  );
}
