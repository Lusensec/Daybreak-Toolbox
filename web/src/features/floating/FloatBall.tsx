import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import {
  MessageSquare, Terminal, Binary, Languages, StickyNote, Wrench, Square, X,
} from "lucide-react";
import { sendCommand, subscribeEvent } from "../../services/ws";
import { useToast } from "../../components/toast";
import { useMenuStore } from "../menu/store";
import { useDetachStore } from "./detachStore";
import "./FloatBall.css";

/**
 * 页面内悬浮球（主视图常驻，z 高于子窗口层）：
 *  - 圆形小球可拖拽换位，位置/收起态持久化 localStorage（刷新保留，子窗口刷新收回不受影响）
 *  - 左键（无拖动）展开快捷面板；右键收起为小圆点（点圆点恢复）
 *  - 面板三组：页面跳转（固定菜单 5 页）/ 工具快启（tool.run，最多 6 个）/ 子窗口（open 幂等，已脱离则移动+置顶）
 */

const LS_KEY = "daybreak.floatball.v1";
const BALL = 44;

interface BallState { x: number; y: number; off: boolean }

/** 初始位置：右下距边 24px；读持久化 */
function loadBall(): BallState {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) {
      const s = JSON.parse(raw) as Partial<BallState>;
      const x = Number.isFinite(s.x) ? s.x! : 0;
      const y = Number.isFinite(s.y) ? s.y! : 0;
      return { x, y, off: s.off === true };
    }
  } catch { /* 损坏按默认 */ }
  return {
    x: window.innerWidth - 24 - BALL,
    y: window.innerHeight - 24 - BALL,
    off: false,
  };
}

/** 面板内页面项（与固定菜单栏同名；图标取 AppShell 顶栏同款） */
const PAGE_ITEMS = [
  { to: "/ai", label: "AI 对话", icon: MessageSquare },
  { to: "/shell", label: "终端管理", icon: Terminal },
  { to: "/codec", label: "编解码", icon: Binary },
  { to: "/translate", label: "汉英翻译", icon: Languages },
  { to: "/note", label: "临时笔记", icon: StickyNote },
];

export function FloatBall() {
  const navigate = useNavigate();
  const toast = useToast();
  const menus = useMenuStore((s) => s.menus);
  const tools = useMenuStore((s) => s.tools);
  const openWin = useDetachStore((s) => s.open);
  const focusWin = useDetachStore((s) => s.focus);
  const detached = useDetachStore((s) => s.detached);

  const [ball, setBall] = useState<BallState>(loadBall);
  const [open, setOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  // 设置页「隐藏悬浮球」（与原生球共享 ball.state）：隐藏时页面内小球也收起为小圆点
  const [setHidden, setSetHidden] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const posRef = useRef(ball);
  posRef.current = ball;

  // 初始拉取 + 订阅 ball.state（设置页/原生球右键改隐藏/置顶都会广播）
  useEffect(() => {
    let alive = true;
    sendCommand("ball.get_state", {})
      .then((r) => { if (alive) setSetHidden(Boolean(r.hidden)); })
      .catch(() => {});
    const un = subscribeEvent("ball.state", (p: unknown) => {
      if (p && typeof p === "object") setSetHidden(Boolean((p as Record<string, unknown>).hidden));
    });
    return () => { alive = false; un(); };
  }, []);

  // 面板外部点击 / Esc 收起
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // 工具快启（菜单序 × 工具序，前 6 个；工具被删后 menu.changed → refresh 自动更新）
  const toolItems = Object.entries(tools)
    .flatMap(([menu, list]) => list.map((t) => ({ menu, name: t.name })))
    .slice(0, 6);

  const persist = (s: BallState) => {
    try { localStorage.setItem(LS_KEY, JSON.stringify(s)); } catch { /* 隐私模式忽略 */ }
  };

  /** 小球指针拖拽（pointer 捕获；位移 < 5px 视为点击 → 展开/收起面板）。
   *  注意：React 合成事件句柄会置空 e.currentTarget，必须先用局部变量捕获元素再挂原生监听 */
  const onPointerDown = (e: React.PointerEvent<HTMLButtonElement>) => {
    if (e.pointerType === "mouse" && e.button !== 0) return; // 右键走 onContextMenu
    const el = e.currentTarget;
    const sx = e.clientX;
    const sy = e.clientY;
    const ox = posRef.current.x;
    const oy = posRef.current.y;
    let moved = false;
    let lastX = ox;
    let lastY = oy;
    setDragging(true);
    try { el.setPointerCapture(e.pointerId); } catch { /* 旧浏览器 */ }
    const mv = (ev: PointerEvent) => {
      const dx = ev.clientX - sx;
      const dy = ev.clientY - sy;
      if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
      lastX = Math.min(window.innerWidth - 8, Math.max(8, ox + dx));
      lastY = Math.min(window.innerHeight - 8, Math.max(8, oy + dy));
      setBall((s) => ({ ...s, x: lastX, y: lastY }));
    };
    const up = () => {
      el.removeEventListener("pointermove", mv);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      setDragging(false);
      if (moved) {
        // 闭包坐标为准（不依赖 posRef 的渲染时序）
        const s = posRef.current;
        persist({ ...s, x: lastX, y: lastY, off: false });
      } else {
        setOpen((o) => !o);
      }
    };
    el.addEventListener("pointermove", mv);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  };

  const toggleOff = () => {
    setBall((s) => {
      const next = { ...s, off: !s.off };
      persist(next);
      return next;
    });
    setOpen(false);
  };

  async function runTool(menu: string, name: string) {
    setOpen(false);
    try {
      await sendCommand("tool.run", { menu, name });
      toast.ok(`已启动「${name}」`);
    } catch (err) {
      toast.err(`启动「${name}」失败：${err instanceof Error ? err.message : String(err)}`);
    }
  }

  function openMenuWindow(menuName: string) {
    setOpen(false);
    // 已脱离：仅置顶；未脱离：在视口中央偏左展开
    if (detached[menuName]) {
      focusWin(menuName);
    } else {
      const x = Math.max(8, Math.round(window.innerWidth * 0.28));
      const y = Math.max(8, Math.round(window.innerHeight * 0.18));
      openWin(menuName, x, y);
    }
  }

  // 面板定位：小球上方居中展开；球在视口上部 320px 内时改向下展开
  const panelBelow = ball.y < 320;
  const panelLeft = Math.min(Math.max(ball.x + BALL / 2 - 130, 8), window.innerWidth - 268);

  if (ball.off || setHidden) {
    // 收起态：18px 小圆点（原位置，系统 logo 缩略、半透明），点按恢复
    // setHidden = 设置页/原生球右键「隐藏悬浮球」→ 点圆点需调 bridge 解除隐藏（ball.state 事件回流）
    const dotTitle = setHidden
      ? "悬浮球已隐藏——点按恢复（或在设置/托盘取消隐藏）"
      : "悬浮球已收起——点按恢复";
    return (
      <button
        type="button"
        className="floatball__dot"
        style={{ left: Math.min(ball.x, window.innerWidth - 22), top: Math.min(ball.y, window.innerHeight - 22) }}
        title={dotTitle}
        onClick={() => {
          setBall((s) => { const next = { ...s, off: false }; persist(next); return next; });
          if (setHidden) {
            void sendCommand("ball.set_hidden", { hidden: false }).catch(() => {});
          }
        }}
      >
        <img src="/logo.png" alt="" draggable={false} />
      </button>
    );
  }

  return (
    <div className="floatball" ref={wrapRef}>
      <div
        className={"floatball__panel" + (open ? " is-open" : "")}
        style={{ left: panelLeft, top: ball.y }}
        data-below={panelBelow ? "1" : "0"}
      >
        <div className="floatball__group">
          <div className="floatball__gtitle">页面</div>
          {PAGE_ITEMS.map((p) => (
            <button
              key={p.to}
              type="button"
              className="floatball__item"
              onClick={() => { setOpen(false); navigate(p.to); }}
            >
              <p.icon size={14} />
              <span>{p.label}</span>
            </button>
          ))}
        </div>

        {toolItems.length > 0 ? (
          <div className="floatball__group">
            <div className="floatball__gtitle">工具快启（前 6 个）</div>
            {toolItems.map((t) => (
              <button
                key={`${t.menu}__${t.name}`}
                type="button"
                className="floatball__item"
                title={`${t.menu} · 启动该工具`}
                onClick={() => { void runTool(t.menu, t.name); }}
              >
                <Wrench size={14} />
                <span>{t.name}</span>
                <small>{t.menu}</small>
              </button>
            ))}
          </div>
        ) : null}

        {menus.length > 0 ? (
          <div className="floatball__group">
            <div className="floatball__gtitle">菜单子窗口</div>
            {menus.map((m) => (
              <button
                key={m.name}
                type="button"
                className="floatball__item"
                title={detached[m.name] ? "已脱离——点击置顶" : "以子窗口打开该菜单"}
                onClick={() => openMenuWindow(m.name)}
              >
                <Square size={14} />
                <span>{m.name}</span>
                {detached[m.name] ? <X size={12} className="floatball__badge" /> : null}
              </button>
            ))}
          </div>
        ) : null}

        <div className="floatball__foot">右键小球收起 · 拖动换位 · Esc 关闭面板</div>
      </div>

      <button
        type="button"
        className={"floatball__ball" + (dragging ? " is-dragging" : "") + (open ? " is-open" : "")}
        style={{ left: ball.x, top: ball.y }}
        title="悬浮球：左键展开 / 拖动换位 / 右键收起"
        onPointerDown={onPointerDown}
        onContextMenu={(e) => { e.preventDefault(); toggleOff(); }}
      >
        <img src="/logo.png" alt="破晓·工具箱" className="floatball__logo" draggable={false} />
      </button>
    </div>
  );
}
