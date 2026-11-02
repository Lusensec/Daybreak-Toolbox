import { useEffect, useRef, useState } from "react";
import { Outlet, NavLink, useLocation } from "react-router";
import { Moon, Sun, Wifi, WifiOff, Settings, Monitor } from "lucide-react";
import { useTheme } from "../theme/ThemeProvider";
import type { ThemeChoice } from "../theme/ThemeProvider";
import { connectBridge, disconnectBridge, useConnStore, sendCommand, fetchBridgeToken } from "../services/ws";
import { SettingsModal } from "./SettingsModal";
import { DynamicMenuNav, NavBarRow, CtxMenu } from "./DynamicMenuNav";
import type { CtxState } from "./DynamicMenuNav";
import { ToastHost, useToast } from "./toast";
import { useSettingsModal } from "../store/settingsModal";
import { bindMenuEvents, useMenuStore, isFixedVisible } from "../features/menu/store";
import { useWheelScrollHorizontal } from "../hooks/useWheelScroll";
import { useDetachStore } from "../features/floating/detachStore";
import { useDetachDrag } from "../features/floating/useDetachDrag";
import { FloatingWindowHost } from "../features/floating/FloatingWindow";
import { FloatBall } from "../features/floating/FloatBall";
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

// bridge 自托管生产模式：同源部署（pnpm build 后由 python -m bridge.main 托管）。
// 此模式下自动取 /api/token 并连接，隐藏 dev 桥接 dock。
const BRIDGE_HOSTED = !import.meta.env.DEV;

// 单按钮主题循环：浅色 → 深色 → 跟随系统 → 浅色（图标展示当前项）
const THEME_NEXT: Record<ThemeChoice, ThemeChoice> = { light: "dark", dark: "system", system: "light" };
const THEME_LABEL: Record<ThemeChoice, string> = { light: "浅色", dark: "深色", system: "跟随系统" };

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
  const { theme, set } = useTheme();
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
    return () => {
      disconnectBridge();
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
      <header className="menu-bar" ref={topBarRef}>
        <div className="menu-brand">
          <img className="menu-brand__logo" src="/logo.png" alt="破晓·工具箱" />
          <span className="menu-title">破晓·工具箱</span>
          <span className="menu-subtitle">Daybreak Toolbox · Web</span>
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
          <div className="theme-toggle-group" role="group" aria-label="主题">
            {/* 单按钮循环切换：浅色 → 深色 → 跟随系统（图标 = 当前主题） */}
            <button
              className="theme-toggle active"
              onClick={() => set(THEME_NEXT[theme])}
              title={`当前：${THEME_LABEL[theme]}，点击切换到「${THEME_LABEL[THEME_NEXT[theme]]}」`}
            >
              {theme === "light" ? <Sun size={16} /> : theme === "dark" ? <Moon size={16} /> : <Monitor size={16} />}
            </button>
          </div>
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

      {/* 页面内悬浮球（快捷面板：页面/工具快启/子窗口；位置持久化） */}
      <FloatBall />

      {/* 全局快捷键监听（panel / 动态菜单 / 固定菜单 / 导航 / 工具；渲染 null） */}
      <GlobalShortcuts />

      {/* 工具箱设置：右侧按钮 / 首页卡 → 模态框操作（通用 / 菜单管理 / 工具管理 / AI 模型设置） */}
      <SettingsModal open={settingsOpen} onClose={closeModal} />

      {/* 全局消息提醒：右上角提示框（高于模态框） */}
      <ToastHost />
    </div>
  );
}
