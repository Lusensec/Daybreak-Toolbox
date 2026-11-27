import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { Outlet, NavLink, useLocation } from "react-router";
import { Wifi, WifiOff, Settings, Maximize, Copy, Minus, X } from "lucide-react";
import { useTheme } from "../theme/ThemeProvider";
import { connectBridge, disconnectBridge, useConnStore, sendCommand, fetchBridgeToken, subscribeEvent } from "../services/ws";
import { DynamicMenuNav, NavBarRow, CtxMenu } from "./DynamicMenuNav";
import type { CtxState } from "./DynamicMenuNav";
import { ToastHost, useToast } from "./toast";
import { PromptDialogHost } from "./PromptDialog";
import { useSettingsModal } from "../store/settingsModal";
import { bindMenuEvents, useMenuStore, isFixedVisible } from "../features/menu/store";
import { useWheelScrollHorizontal } from "../hooks/useWheelScroll";
import { useDetachStore } from "../features/floating/detachStore";
import { useDetachDrag } from "../features/floating/useDetachDrag";
import { FloatingWindowHost } from "../features/floating/FloatingWindow";
import { GlobalShortcuts } from "../features/shortcuts/GlobalShortcuts";
import { bindShortcutEvents } from "../features/shortcuts/store";
import { bindSshEvents } from "../features/ssh/store";
import "./AppShell.css";

const NAV = [
  { to: "/", label: "首页", end: true },
  { to: "/ai", label: "AI 对话" },
  { to: "/shell", label: "终端管理" },
  { to: "/codec", label: "编解码" },
  { to: "/translate", label: "汉英翻译" },
  { to: "/note", label: "临时笔记" },
];

/** 工具箱设置模态框懒加载（设置 UI 较重：10 个标签页 + 表单/列表；仅在打开时才需要） */
const SettingsModalLazy = lazy(() => import("./SettingsModal").then((m) => ({ default: m.SettingsModal })));

// bridge 自托管生产模式：同源部署（pnpm build 后由 python -m bridge.main 托管）。
// 此模式下自动取 /api/token 并连接，隐藏 dev 桥接 dock。
const BRIDGE_HOSTED = !import.meta.env.DEV;

/**
 * 固定系统菜单按钮（可拖出顶栏脱离为子窗口）：
 *  - useDetachDrag(reorderable=false)：栏内松手=不重排（固定顺序），拖出顶栏=开子窗口
 *  - 已脱离态：虚线+降透明，点击 = 收回菜单栏（不跳路由）
 *  - 未脱离：普通 NavLink 路由跳转 + 右键 显示/隐藏
 *  - 注意：NavLink 是 <a>，浏览器原生可拖拽（真鼠标按住移动会触发 link-drag，
 *    掐断 pointer capture → 脱离手势必死）；必须 draggable=false + 拦截 dragstart
 *    （用户菜单按钮是 <button> 无此问题）
 */
function FixedNavButton({ to, label, end, barRef, onCtx }: {
  to: string; label: string; end?: boolean;
  barRef: React.RefObject<HTMLElement | null>;
  onCtx: (e: React.MouseEvent, name: string) => void;
}) {
  const { startDrag, suppressClick, ghost } = useDetachDrag({ name: label, reorderable: false, barRef });
  const hoverMe = useDetachStore((s) => s.hoverTarget === label);
  const detached = useDetachStore((s) => label in s.detached);
  const close = useDetachStore((s) => s.close);
  return (
    <>
      <NavLink
        to={to}
        end={end}
        data-detach-btn={label}
        draggable={false}
        onDragStart={(e) => e.preventDefault()}
        className={({ isActive }) =>
          "nav-link" + (isActive ? " active" : "") +
          (detached ? " nav-link--detached" : "") +
          (hoverMe ? " nav-link--drop-target" : "")
        }
        title={detached ? "已脱离为子窗口，点击收回菜单栏" : "右键可 显示/隐藏 该菜单栏；拖出顶栏可脱离为子窗口"}
        onPointerDown={startDrag}
        onClick={(e) => {
          if (suppressClick()) { e.preventDefault(); return; }
          if (detached) { e.preventDefault(); close(label); }
        }}
        onContextMenu={(e) => { e.preventDefault(); onCtx(e, label); }}
      >
        {label}
        {detached ? <span className="nav-link__detached-tag">已脱离</span> : null}
      </NavLink>
      {ghost}
    </>
  );
}

export default function AppShell() {
  const { isDark } = useTheme();
  const conn = useConnStore((s) => s.status);
  const lastError = useConnStore((s) => s.lastError);
  const [token, setToken] = useState(() => localStorage.getItem("daybreak.token") ?? "");
  const [connected, setConnected] = useState(false);
  const [booting, setBooting] = useState(BRIDGE_HOSTED);
  const { open: settingsOpen, openModal, closeModal } = useSettingsModal();
  const location = useLocation();
  const menuNavRef = useRef<HTMLElement>(null);
  const topBarRef = useRef<HTMLElement>(null); // 顶栏参照 rect（判定「栏内/栏外」脱离边界）
  useWheelScrollHorizontal(menuNavRef);
  const toast = useToast();
  // 固定菜单栏显隐（config.json __fixed_menu_visible__，menu.changed 自动刷新）+ 右键菜单
  const fixedVisible = useMenuStore((s) => s.fixedVisible);
  const [fixedCtx, setFixedCtx] = useState<CtxState | null>(null);

  // ---- 自定义窗口控件（v2.0.8 起窗口形态为无边框：顶栏驱动 移动/最大化/拉伸/关闭；非窗口形态不渲染）----
  const [windowed, setWindowed] = useState(false);
  const [maximized, setMaximized] = useState(false);
  // v2.0.15「关闭后进入最小化」状态（settings.get；仅影响 X 按钮提示文案——行为由桥接侧统一判定）
  const [closeToTray, setCloseToTray] = useState<boolean | null>(null);
  const dragState = useRef<{ active: boolean; sx: number; sy: number; ox: number; oy: number } | null>(null);

  /** 顶栏非交互目标判定：按钮/链接/输入控件/可脱离项 不参与拖移（品牌区、栏间隙可拖） */
  function isHeaderDragTarget(t: EventTarget | null): boolean {
    if (!(t instanceof HTMLElement)) return false;
    return !t.closest("button, a, input, select, textarea, [draggable='true']");
  }

  /** 顶栏拖拽移动窗口：mousedown 取一次窗口基准 rect → mousemove rAF 节流 window.move（DIP 增量，逻辑像素一致） */
  // v2.0.17：拖拽/拉伸流「至多一笔在途」背压——前一笔 window.move/set_rect 未 ACK 时本帧跳过
  //（最新坐标由下一 rAF 携带）；RTT 快时无感，RTT 慢时平滑合并而非成批追帧（防队列堆积阶梯跳变）
  const geoInFlight = useRef(0);
  function sendGeo(cmd: "window.move" | "window.set_rect", payload: Record<string, unknown>) {
    if (geoInFlight.current > 0) return;
    geoInFlight.current += 1;
    void sendCommand(cmd, payload).catch(() => {}).finally(() => {
      geoInFlight.current -= 1;
    });
  }

  function onHeaderDragStart(e: React.MouseEvent) {
    if (!windowed || e.button !== 0 || !isHeaderDragTarget(e.target)) return;
    void (async () => {
      try {
        const r = (await sendCommand("window.get_rect", {})) as { rect?: { x: number; y: number; width: number; height: number } | null };
        const rect = r?.rect;
        if (!rect) return;
        const d = { active: true, sx: e.screenX, sy: e.screenY, ox: rect.x, oy: rect.y };
        dragState.current = d;
        let queued = false;
        let lx = e.screenX, ly = e.screenY;
        const onMove = (ev: MouseEvent) => {
          lx = ev.screenX; ly = ev.screenY;
          if (queued || !d.active) return;
          queued = true;
          requestAnimationFrame(() => {
            queued = false;
            if (!d.active) return;
            sendGeo("window.move", { x: d.ox + (lx - d.sx), y: d.oy + (ly - d.sy) });
          });
        };
        const onUp = () => {
          d.active = false;
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
        };
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      } catch { /* 桥接未就绪：不拖 */ }
    })();
  }

  /** 顶栏双击 = 最大化/还原（模拟原生标题栏行为；交互目标除外） */
  function onHeaderDblClick(e: React.MouseEvent) {
    if (windowed && isHeaderDragTarget(e.target)) void toggleMaximize();
  }

  /** 最大化/还原 toggle：后端管几何（Windows 手动工作区版，避开无边框盖任务栏），web 只切图标 */
  async function toggleMaximize() {
    try {
      const r = (await sendCommand("window.maximize", {})) as { ok?: boolean; maximized?: boolean };
      if (r?.ok) setMaximized(Boolean(r.maximized));
    } catch { /* 桥接未就绪 */ }
  }

  /** 边缘/角落拉伸（v2.0.10：左/右/下边缘 + 左下/右下角；替换 v2.0.8 单一右下角手柄）。
      基准 rect 一次取 → mousemove rAF 节流；左缘/左下先 window.move（新左上角）再 window.resize
      （后端 N|W 固定点，顺序保证左上角跟随）；客户端镜像最小 960×600（与后端 _clamp_window_size 同源）。
      最大化中拖边缘 = 原生语义「自动还原后拉伸」：mousedown 时若处于最大化先还原（服务端几何驱动）。 */
  const EDGE_MIN_W = 960;
  const EDGE_MIN_H = 600;
  type EdgeZone = "left" | "right" | "bottom" | "bl" | "br";

  function onEdgeResizeStart(zone: EdgeZone) {
    return (e: React.MouseEvent) => {
      if (!windowed || e.button !== 0) return;
      e.preventDefault();
      void (async () => {
        try {
          let rectRes = (await sendCommand("window.get_rect", {})) as { rect?: { x: number; y: number; width: number; height: number } | null };
          let rect = rectRes?.rect;
          if (!rect) return;
          // 最大化中拖边缘：先还原（服务端按几何判定执行还原），再取新几何为基准
          if (maximized) {
            const m = (await sendCommand("window.maximize", {})) as { ok?: boolean; maximized?: boolean };
            if (m?.ok) setMaximized(Boolean(m.maximized));
            rectRes = (await sendCommand("window.get_rect", {})) as { rect?: { x: number; y: number; width: number; height: number } | null };
            rect = rectRes?.rect;
            if (!rect) return;
          }
          let active = true;
          const sx = e.screenX, sy = e.screenY;
          const ox = rect.x, oy = rect.y, ow = rect.width, oh = rect.height;
          let queued = false;
          let lx = sx, ly = sy;
          const onMove = (ev: MouseEvent) => {
            lx = ev.screenX; ly = ev.screenY;
            if (queued || !active) return;
            queued = true;
            requestAnimationFrame(() => {
              queued = false;
              if (!active) return;
              const dx = lx - sx, dy = ly - sy;
              let w = ow, h = oh, x = ox, y = oy;
              if (zone === "right" || zone === "br") w = ow + dx;
              if (zone === "bottom" || zone === "bl") h = oh + dy;
              if (zone === "left" || zone === "bl") {
                w = Math.max(EDGE_MIN_W, ow - dx);
                x = ox + (ow - w); // 左上角随左缘右移
              }
              w = Math.max(EDGE_MIN_W, w); // 客户端镜像钳制（后端 _clamp_window_size 双保险）
              h = Math.max(EDGE_MIN_H, h);
              // 位置+大小一次原子提交（window.set_rect 单次 SetWindowPos）：
              // 旧版 左缘=move+resize 两步快连发会被 WinForms UI 线程吞一笔 → 卡顿/位置钉死
              // v2.0.17：走 sendGeo（至多一笔在途背压，防慢 RTT 队列堆积成批追帧）
              sendGeo("window.set_rect", { x, y, width: w, height: h });
            });
          };
          const onUp = () => {
            active = false;
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseup", onUp);
          };
          window.addEventListener("mousemove", onMove);
          window.addEventListener("mouseup", onUp);
        } catch { /* 桥接未就绪 */ }
      })();
    };
  }

  /** 固定菜单右键：隐藏 / 显示菜单栏（参数存 config.json，1 显示 / 0 隐藏） */
  async function toggleFixedMenu(name: string) {
    const show = !isFixedVisible(fixedVisible, name);
    try {
      await sendCommand("menu.set_fixed_visible", { name, visible: show });
      toast.ok(show ? `菜单栏「${name}」已显示` : `菜单栏「${name}」已隐藏（可在 工具箱设置→菜单栏展示 恢复）`);
    } catch (e) {
      toast.err(`操作失败：${e instanceof Error ? e.message : e}`);
    }
  }

  // v2.0.17：窗体背景色随主题同步（下边框拉伸时 WebView2 渲染间隙露出的条带与页面同色，
  // 白闪不可见；颜色取自 theme/tokens.css 的 --bg）
  useEffect(() => {
    if (!windowed) return;
    const rgb = isDark ? [0x1e, 0x1f, 0x24] : [0xf4, 0xf6, 0xf8];
    void sendCommand("window.set_background", { r: rgb[0], g: rgb[1], b: rgb[2] }).catch(() => {});
  }, [windowed, isDark]);

  // 路由切到固定功能页（非工具画布）时隐藏导航栏行（旧版：离开工具菜单后导航栏消失）
  useEffect(() => {
    if (!location.pathname.startsWith("/tools/")) {
      useMenuStore.getState().clearActive();
    }
  }, [location]);

  // 生产模式：挂载时自动取 token + 连接（无需手动粘贴）
  useEffect(() => {
    if (!BRIDGE_HOSTED) return;
    let cancelled = false;
    (async () => {
      const t = await fetchBridgeToken();
      if (cancelled) return;
      if (t) {
        localStorage.setItem("daybreak.token", t);
        setToken(t);
        setBooting(false);
        setConnected(true);
      } else {
        setBooting(false);
        useConnStore.setState({ lastError: "无法获取桥接 token（/api/token）" });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // 连接桥接（dev 手动点连接；prod 由上方自动置 connected=true）
  useEffect(() => {
    if (!connected) return;
    if (token) localStorage.setItem("daybreak.token", token);
    connectBridge({ token: token || undefined }).catch((e) => {
      useConnStore.setState({ lastError: String(e) });
    });
    const sub = subscribeOnStatus();
    // 桥接在线后拉取动态菜单 + 订阅 menu.changed（设置改菜单/工具时顶栏同步）
    bindMenuEvents();
    // 快捷键表：首次加载 + 订阅 shortcut.changed（即时生效）
    bindShortcutEvents();
    // SSH 主机表：首次加载 + 订阅 ssh.hosts.changed / ssh.closed（终端设置改主机后下拉框即时同步）
    bindSshEvents();
    // 窗口形态探测：无边框窗口（frameless）才渲染 最大化/关闭X/拖移/拉伸 控件（浏览器/服务形态隐藏）
    sendCommand("app.env", {})
      .then((r) => { if ((r as { windowed?: boolean }).windowed) { setWindowed(true); } })
      .catch(() => {});
    // v2.0.15：关闭行为提示（X 按钮 tooltip）——设置即时生效，改键时经 settings.changed 同步
    sendCommand("settings.get", {})
      .then((r) => setCloseToTray(Boolean((r as { close_to_tray?: boolean }).close_to_tray)))
      .catch(() => {});
    const unsubSettings = subscribeEvent("settings.changed", (p) => {
      setCloseToTray(Boolean((p as { close_to_tray?: boolean }).close_to_tray));
    });
    return () => {
      disconnectBridge();
      unsubSettings();
      sub();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected]);

  function subscribeOnStatus() {
    const s = useConnStore.subscribe((state) => {
      setConnected(state.status === "online" || state.status === "reconnecting" || state.status === "connecting");
    });
    return s;
  }

  // 生产模式下手动“重试连接”：重新取 token 并置位自动连接
  async function retryAutoConnect() {
    setBooting(true);
    const t = await fetchBridgeToken();
    if (t) {
      localStorage.setItem("daybreak.token", t);
      setToken(t);
      setConnected(true);
    } else {
      setBooting(false);
      useConnStore.setState({ lastError: "无法获取桥接 token（/api/token）" });
    }
  }

  const online = conn === "online";

  return (
    <div className="app-shell">
      <header className="menu-bar" ref={topBarRef} onMouseDown={onHeaderDragStart} onDoubleClick={onHeaderDblClick}>
        <div className="menu-brand">
          <img className="menu-brand__logo" src={isDark ? "/logo.png" : "/logo-light.png"} alt="破晓·工具箱" />
          <span className="menu-title">破晓·工具箱</span>
        </div>
        <nav className="menu-nav" ref={menuNavRef}>
          {/* 顺序：首页 → 动态加载的用户菜单 → 固定功能面板（均按 菜单栏展示 参数 1/0 显隐；可拖出顶栏脱离为子窗口） */}
          {isFixedVisible(fixedVisible, "首页") ? (
            <FixedNavButton
              to="/"
              label="首页"
              barRef={topBarRef}
              onCtx={(e, name) => setFixedCtx({ x: e.clientX, y: e.clientY, target: { kind: "menu", name } })}
            />
          ) : null}
          <DynamicMenuNav barRef={topBarRef} />
          {NAV.slice(1)
            .filter((item) => isFixedVisible(fixedVisible, item.label))
            .map((item) => (
              <FixedNavButton
                key={item.to}
                to={item.to}
                label={item.label}
                end={item.end}
                barRef={topBarRef}
                onCtx={(e, name) => setFixedCtx({ x: e.clientX, y: e.clientY, target: { kind: "menu", name } })}
              />
            ))}
          {fixedCtx ? (
            <CtxMenu
              state={fixedCtx}
              items={[
                {
                  label: isFixedVisible(fixedVisible, fixedCtx.target.name) ? "隐藏菜单栏" : "显示菜单栏",
                  icon: "eye",
                  run: () => toggleFixedMenu(fixedCtx.target.name),
                },
              ]}
              onClose={() => setFixedCtx(null)}
            />
          ) : null}
        </nav>
        <div className="menu-bar-right">
          <button className="settings-btn" onClick={() => openModal()} title="工具箱设置">
            <Settings size={16} /> 工具箱设置
          </button>
          {/* 自定义窗口控件（仅无边框窗口形态：原生标题栏已移除，窗口操作在此；顺序=原生 最小化/最大化/关闭）
              主题切换已移除（v2.0.9 起）：主题在「工具箱设置 → 通用设置 → 外观」配置，顶栏 logo 自动跟随 */}
          {windowed ? (
            <>
              <button className="win-ctrl" onClick={() => { void sendCommand("window.minimize", {}).catch(() => {}); }} title="最小化窗口">
                <Minus size={16} />
              </button>
              <button className="win-ctrl" onClick={() => void toggleMaximize()} title={maximized ? "还原窗口" : "最大化窗口"}>
                {maximized ? <Copy size={16} /> : <Maximize size={16} />}
              </button>
              <button
                className="win-ctrl win-ctrl--close"
                onClick={() => { void sendCommand("app.quit", {}).catch(() => {}); }}
                title={closeToTray ? "最小化到托盘（托盘菜单可重新打开；托盘「退出」为真正退出）" : "关闭破晓·工具箱"}
              >
                <X size={16} />
              </button>
            </>
          ) : null}
        </div>
      </header>

      {/* 导航栏行：菜单栏正下方常驻第二行（旧版 create_Navigation_Bar 位置）。
          点顶栏动态菜单按钮显示；点固定功能导航 / 再次点菜单则隐藏 */}
      <NavBarRow />

      <main className="content">
        <Outlet />

        {/* 生产（bridge 自托管）模式下确实断开时给出明确提示（连接中/重连中由状态栏提示） */}
        {BRIDGE_HOSTED && conn === "disconnected" && !booting ? (
          <div className="bridge-dock bridge-dock--offline">
            <span className="bridge-dock__msg">
              未连接到桥接服务。{lastError ? `原因：${lastError}` : "请确认 python -m bridge.main 已启动。"}
            </span>
            <button onClick={() => void retryAutoConnect()}>重试连接</button>
          </div>
        ) : null}

        {/* 开发期桥接连接条（生产模式自动连接，隐藏此条） */}
        {!BRIDGE_HOSTED ? (
          <div className="bridge-dock">
            <label>
              桥接 token（dev）：
              <input
                type="text"
                value={token}
                placeholder="粘贴 config/bridge_secrets.json 的 token"
                onChange={(e) => setToken(e.target.value)}
              />
            </label>
            <button
              onClick={() => {
                if (connected) {
                  disconnectBridge();
                  setConnected(false);
                } else {
                  setConnected(true);
                }
              }}
            >
              {connected ? "断开" : "连接"}
            </button>
            <button
              onClick={async () => {
                try {
                  const r = await sendCommand("echo", { msg: "ping" });
                  alert(`echo 回传: ${JSON.stringify(r)}`);
                } catch (e) {
                  alert(`echo 失败: ${e}`);
                }
              }}
              disabled={!online}
            >
              试 echo
            </button>
          </div>
        ) : null}
      </main>

      <footer className="status-bar">
        <span className="status-text">就绪 · 破晓·工具箱</span>
        <span className="status-badge" data-state={online ? "online" : "offline"} title={lastError ?? ""}>
          {online ? <Wifi size={13} /> : <WifiOff size={13} />}
          &nbsp;{conn === "online" ? "已连接" : conn === "reconnecting" ? "重连中…" : conn === "connecting" ? "连接中…" : "未连接"}
        </span>
      </footer>

      {/* 菜单栏拖出脱离的子窗口（浮动层，纯 UI 状态；刷新全部收回栏内） */}
      <FloatingWindowHost />

      {/* 全局快捷键监听（panel / 动态菜单 / 固定菜单 / 导航 / 工具；渲染 null） */}
      <GlobalShortcuts />

      {/* 工具箱设置：右侧按钮 / 首页卡 → 模态框操作（通用 / 菜单管理 / 工具管理 / AI 模型设置） */}
      {settingsOpen ? (
        <Suspense fallback={null}>
          <SettingsModalLazy open={settingsOpen} onClose={closeModal} />
        </Suspense>
      ) : null}

      {/* 全局消息提醒：右上角提示框（高于模态框） */}
      <ToastHost />

      {/* 全局重命名对话框（替代 window.prompt；顶栏右键 / 设置页 / 子窗口 共用） */}
      <PromptDialogHost />

      {/* 全边缘拉伸手柄（v2.0.10，仅无边框窗口形态）：左/右缘 6px、下缘 6px + 左下/右下角 14px，
          任意边缘位置可拖动调整窗口大小（最小 960×600 客户端镜像 + 后端 _clamp_window_size 双保险）；
          顶缘不做（顶栏是拖移区）；模态层打开时边缘被盖住不可拉伸（可接受） */}
      {windowed ? (
        <>
          <div className="win-edge win-edge--left" onMouseDown={onEdgeResizeStart("left")} title="拖动调整窗口大小" />
          <div className="win-edge win-edge--right" onMouseDown={onEdgeResizeStart("right")} title="拖动调整窗口大小" />
          <div className="win-edge win-edge--bottom" onMouseDown={onEdgeResizeStart("bottom")} title="拖动调整窗口大小" />
          <div className="win-edge win-edge--bl" onMouseDown={onEdgeResizeStart("bl")} title="拖动调整窗口大小" />
          <div className="win-edge win-edge--br" onMouseDown={onEdgeResizeStart("br")} title="拖动调整窗口大小" />
        </>
      ) : null}
    </div>
  );
}
