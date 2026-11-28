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
import "./AppShell.css";

/** 工具箱设置模态框懒加载（设置 UI 较重：多个标签页 + 表单/列表；仅在打开时才需要） */
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
  // v2.0.18：品牌区版本号（app.env → version；服务形态/旧桥接无该字段时不渲染）
  const [appVersion, setAppVersion] = useState<string | null>(null);

  /** 顶栏非交互目标判定：按钮/链接/输入控件/可脱离项/图片 不参与拖移。
   *  v2.0.20：显式排除 img —— <img> 默认可原生拖拽（draggable IDL=true 但无属性，
   *  `[draggable='true']` 选择器匹配不到），原生图片拖拽会吞掉 mouseup，窗口卡在拖拽态。
   *  v2.1.2：收窄热区 —— 菜单按钮行（.menu-nav）与右侧控件行（.menu-bar-right）整块排除。
   *  这两行是 flex 容器，按钮之间的 gap 空白其 target 就是容器本身，旧判定会放行，
   *  导致「想点菜单却点进缝里 → 整个窗口被拖走」。现在只有品牌区与它们的真空白可拖。 */
  function isHeaderDragTarget(t: EventTarget | null): boolean {
    if (!(t instanceof HTMLElement)) return false;
    if (t.closest("button, a, input, select, textarea, img, [draggable='true']")) return false;
    if (t.closest(".menu-nav, .menu-bar-right")) return false;
    return true;
  }

  /** 顶栏拖拽移动窗口：mousedown 取一次窗口基准 rect → mousemove rAF 节流 window.move（DIP 增量）。
   *  v2.0.17：「至多一笔在途」背压（最新坐标由下一 rAF 携带，慢 RTT 平滑合并而非成批追帧）。
   *  v2.0.19：自适应节流——RTT 的 EMA > 16ms 时按 RTT 降频，给 WebView2 合成留时间。
   *  v2.0.20：窗口尺寸固定（不可拉伸）后只剩「移动」，不再调用 drag_begin/drag_end——
   *  v2.0.19 的 WM_SETREDRAW 挂起会冻死 WebView2 合成（点击左上角黑/白屏的根因）。 */
  const DRAG_THRESHOLD = 3;  // px：位移小于该值视为单击，不发任何几何命令
  const geoInFlight = useRef(0);
  const geoRtt = useRef(8);       // 最近 RTT 的指数移动平均（ms）
  const geoLastSent = useRef(0);  // 上一帧发出时刻（performance.now()）
  /** v2.1.2：当前顶栏拖拽的拆除句柄。
   *  旧版只在 mouseup 里置 active=false 并摘监听器——一旦 mouseup 丢失（窗口外松手 /
   *  触发 pointercancel / 窗口失焦 / 切后台），监听器与 active 状态会永久残留，
   *  此后在主内容区（如临时笔记）随便划鼠标都会被算成「继续拖窗口」。 */
  const dragTeardown = useRef<(() => void) | null>(null);
  function sendGeo(payload: { x: number; y: number }) {
    if (geoInFlight.current > 0) return;
    const now = performance.now();
    // RTT > 16ms（一帧预算）→ 冷却 = RTT×1.25（封顶 64ms），给 WebView2 留合成时间；否则 ~8ms 节流
    const cooldown = geoRtt.current > 16 ? Math.min(geoRtt.current * 1.25, 64) : 8;
    if (now - geoLastSent.current < cooldown) return;
    geoLastSent.current = now;
    geoInFlight.current += 1;
    const t0 = now;
    void sendCommand("window.move", payload).catch(() => {}).finally(() => {
      const rtt = performance.now() - t0;
      geoRtt.current = geoRtt.current * 0.7 + rtt * 0.3;  // EMA 平滑，避免单帧抖动误触发降频
      geoInFlight.current -= 1;
    });
  }

  function onHeaderDragStart(e: React.MouseEvent) {
    if (!windowed || e.button !== 0 || !isHeaderDragTarget(e.target)) return;
    // v2.1.2：开新拖拽前先拆掉上一轮残留（上一轮 mouseup 可能从未到达）
    dragTeardown.current?.();
    void (async () => {
      try {
        const r = (await sendCommand("window.get_rect", {})) as { rect?: { x: number; y: number; width: number; height: number } | null };
        const rect = r?.rect;
        if (!rect) return;
        const d = { active: true, sx: e.screenX, sy: e.screenY, ox: rect.x, oy: rect.y };
        let moved = false;   // 超过阈值才进入拖拽（单击/点 logo 不发命令、不进入拖拽态）
        let queued = false;
        let lx = e.screenX, ly = e.screenY;

        /** 幂等拆除：状态复位 + 摘掉全部监听器（含丢失 mouseup 的兜底路径） */
        const teardown = () => {
          if (!d.active) return;
          d.active = false;
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          window.removeEventListener("pointercancel", teardown);
          window.removeEventListener("blur", teardown);
          document.removeEventListener("visibilitychange", onVisibility);
          dragTeardown.current = null;
        };
        const onVisibility = () => { if (document.hidden) teardown(); };

        const onMove = (ev: MouseEvent) => {
          lx = ev.screenX; ly = ev.screenY;
          if (!d.active) return;
          // v2.1.2：左键已松开（mouseup 丢失的情形）→ 立刻拆除，
          // 杜绝「不按鼠标在主内容区滑动就把窗口带走」
          if (ev.buttons === 0) { teardown(); return; }
          if (!moved && Math.abs(lx - d.sx) < DRAG_THRESHOLD && Math.abs(ly - d.sy) < DRAG_THRESHOLD) return;
          moved = true;
          if (queued) return;
          queued = true;
          requestAnimationFrame(() => {
            queued = false;
            if (!d.active) return;
            sendGeo({ x: d.ox + (lx - d.sx), y: d.oy + (ly - d.sy) });
          });
        };
        const onUp = () => {
          const wasActive = d.active;
          const nx = d.ox + (lx - d.sx);
          const ny = d.oy + (ly - d.sy);
          const didMove = moved;
          teardown();
          // 补发最终位置（节流可能跳过最后一帧）→ 窗口精确停在光标处；单击则完全不动
          if (wasActive && didMove) {
            void sendCommand("window.move", { x: nx, y: ny }).catch(() => {});
          }
        };

        dragTeardown.current = teardown;
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
        window.addEventListener("pointercancel", teardown);
        window.addEventListener("blur", teardown);
        document.addEventListener("visibilitychange", onVisibility);
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

  /** v2.0.20：窗口尺寸固定为主屏工作区 80%，边缘/角落拉伸手柄与相关几何逻辑已移除
   *  （后端 resizable=False + _clamp_window_size 固定值双保险）。仅保留 最大化/还原。 */


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

  // v2.1.2：卸载时拆掉可能残留的顶栏拖拽监听（热重载/路由卸载也不留僵尸）
  useEffect(() => () => { dragTeardown.current?.(); }, []);

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
    // 窗口形态探测：无边框窗口（frameless）才渲染 最大化/关闭X/拖移/拉伸 控件（浏览器/服务形态隐藏）
    sendCommand("app.env", {})
      .then((r) => {
        const env = r as { windowed?: boolean; version?: string };
        if (env.windowed) { setWindowed(true); }
        if (typeof env.version === "string" && env.version) { setAppVersion(env.version); }
      })
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
          <img
            className="menu-brand__logo"
            src={isDark ? "/logo.png" : "/logo-light.png"}
            alt="破晓·工具箱"
            draggable={false}
          />
          <div className="menu-brand__text">
            <span className="menu-title">破晓·工具箱</span>
            {/* v2.0.20：版本号（椭圆底色胶囊）+ 紧邻右侧的桥接连接状态；
                原底部状态栏（就绪 · 破晓·工具箱 / 已连接）已移除，状态收敛到此处 */}
            <div className="menu-brand__meta">
              {appVersion ? <span className="menu-brand__version">v{appVersion}</span> : null}
              <span className="menu-brand__conn" data-state={online ? "online" : "offline"} title={lastError ?? ""}>
                {online ? <Wifi size={11} /> : <WifiOff size={11} />}
                <span>
                  {conn === "online" ? "已连接" : conn === "reconnecting" ? "重连中" : conn === "connecting" ? "连接中" : "未连接"}
                </span>
              </span>
            </div>
          </div>
        </div>
        <nav className="menu-nav" ref={menuNavRef}>
          {/* 顺序：首页 → 动态加载的用户菜单（均按 菜单栏展示 参数 1/0 显隐；可拖出顶栏脱离为子窗口）。
              v2.1.3：AI 对话 / 终端管理 / 编解码 / 汉英翻译 / 临时笔记 已移除，固定菜单只剩首页 */}
          {isFixedVisible(fixedVisible, "首页") ? (
            <FixedNavButton
              to="/"
              label="首页"
              end
              barRef={topBarRef}
              onCtx={(e, name) => setFixedCtx({ x: e.clientX, y: e.clientY, target: { kind: "menu", name } })}
            />
          ) : null}
          <DynamicMenuNav barRef={topBarRef} />
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

      {/* v2.0.20：底部状态栏已移除（「就绪 · 破晓·工具箱」+ 已连接徽标）——
          连接状态移至顶栏品牌区版本号右侧；主内容区因此多出 28px 高度 */}

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

      {/* v2.0.20：全边缘/角落拉伸手柄（.win-edge-*）已移除——窗口固定为主屏工作区 80%，
          仅保留顶栏 最大化/还原 与关闭；无边框窗口不再响应任何边缘拖拽拉伸 */}
    </div>
  );
}
