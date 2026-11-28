import { Suspense, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { Package, Plus, Loader2 } from "lucide-react";
import { sendCommand } from "../../services/ws";
import { useMenuStore } from "../menu/store";
import { useSettingsModal } from "../../store/settingsModal";
import { FIXED_MENUS } from "../menu/fixedMenus";
import { useWheelScrollHorizontal } from "../../hooks/useWheelScroll";
import { CtxMenu, ctxItemsFor, type CtxState } from "../../components/DynamicMenuNav";
import { HomePage } from "../../pages/HomePage";
import "../../pages/ToolCanvas.css";

/** 固定系统菜单 → 页面组件（与 App.tsx 路由表一一对应；全局单例状态多窗共享，用户已确认）。
 *  v2.1.3：AI 对话 / 终端管理 / 编解码 / 汉英翻译 / 临时笔记 已移除，固定菜单只剩「首页」。 */
const FIXED_CONTENT: Record<string, React.ComponentType> = {
  首页: HomePage,
};

/** 懒块占位（子窗口内）：加载完成前显示一行提示 */
function ContentLoader() {
  return <div className="tool-canvas__empty"><Loader2 size={16} className="spin" /> 加载页面中…</div>;
}

export function isFixedMenu(name: string): boolean {
  return FIXED_MENUS.includes(name);
}

/** 子窗口标题栏色点颜色（固定菜单缺省蓝；用户菜单取 config menu_color） */
export function menuDotColor(name: string): string {
  const m = useMenuStore.getState().menus.find((x) => x.name === name);
  return m?.menu_color || "#2980b9";
}

/** 子窗口正文：固定菜单 → 页面组件（Suspense 包懒块）；用户菜单 → 轻量工具浮层画布（不接主路由） */
export function renderMenuContent(name: string): React.ReactNode {
  const C = FIXED_CONTENT[name];
  if (C) return <Suspense fallback={<ContentLoader />}><C /></Suspense>;
  return <FloatingMenuCanvas menu={name} />;
}

interface ToolItem {
  工具名称: string;
  工具路径: string;
  工具使用: string;
  启动方式: string;
  工具命令: string;
  active: boolean;
}

/**
 * 用户菜单的「轻量工具画布」：导航行 + 工具网格（复用 tool.grid / menu.changed / 置灰 / 下载回写，
 * 不复用 ToolCanvas —— 避免与主路由 /tools/:menu/:nav 联动，子窗口选 nav 不影响主画布）。
 *
 * 导航行与主视图 NavBarRow **同款**：.nav-bar-row 单行按钮（原顺序、可拖拽重排 menu.reorder_nav、
 * 右键重命名/删除、滚轮横滚）；仅点击切换的是本浮层自己的 nav 状态，不跳主路由。
 */
export function FloatingMenuCanvas({ menu }: { menu: string }) {
  const menus = useMenuStore((s) => s.menus);
  const info = menus.find((m) => m.name === menu);
  const navs: string[] = info?.navigation_bar_name ?? [];
  const [nav, setNav] = useState(navs[0] ?? "首页");
  const [tools, setTools] = useState<ToolItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const openSettings = useSettingsModal((s) => s.openModal);
  const navigate = useNavigate();
  const rowRef = useRef<HTMLDivElement>(null);
  const dragFrom = useRef<number | null>(null);
  const [dragTo, setDragTo] = useState<number | null>(null);
  const [ctx, setCtx] = useState<CtxState | null>(null);
  useWheelScrollHorizontal(rowRef, navs.length > 0);

  // nav 跟随菜单数据（menu.changed 刷新后若当前 nav 被删 → 回退首个）
  useEffect(() => {
    if (navs.length && !navs.includes(nav)) setNav(navs[0] ?? "首页");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [menu, navs.join("|")]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    sendCommand("tool.grid", { menu, nav })
      .then((r) => alive && setTools((r.tools ?? []) as ToolItem[]))
      .catch((e) => alive && setErr(String(e instanceof Error ? e.message : e)))
      .finally(() => alive && setLoading(false));
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [menu, nav]);

  async function runTool(toolName: string) {
    setBusy(toolName);
    try {
      await sendCommand("tool.run", { menu, name: toolName });
      const r2 = await sendCommand("tool.grid", { menu, nav }); // 下载回写后刷新
      setTools((r2.tools ?? []) as ToolItem[]);
    } catch { /* 执行失败由全局 toast 通道提示 */ }
    finally { setBusy(""); }
  }

  if (!info) {
    return <div className="tool-canvas__empty tool-canvas__empty--err">该菜单不存在（可能已被删除）</div>;
  }

  return (
    <div className="tool-canvas float-canvas">
      {/* 导航行：与主视图 NavBarRow 完全同款（单行按钮、原顺序、拖拽重排、右键菜单） */}
      {navs.length > 0 ? (
        <div className="nav-bar-row float-canvas__row" ref={rowRef}>
          {navs.map((n, i) => (
            <button
              key={n}
              className={
                "nav-bar-row__btn" +
                (n === nav ? " active" : "") +
                (dragTo === i ? " drop-target" : "")
              }
              draggable={n !== "首页"}
              onClick={() => setNav(n)}
              onContextMenu={(e) => {
                e.preventDefault();
                setCtx({ x: e.clientX, y: e.clientY, target: { kind: "nav", name: n } });
              }}
              onDragStart={(e) => {
                if (n === "首页") return; // 「首页」固定首位，自身不可拖
                dragFrom.current = i;
                e.dataTransfer.effectAllowed = "move";
                try { e.dataTransfer.setData("text/plain", n); } catch { /* 旧浏览器 */ }
              }}
              onDragOver={(e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "move";
                if (i !== dragTo) setDragTo(i);
              }}
              onDrop={() => {
                const from = dragFrom.current;
                dragFrom.current = null;
                setDragTo(null);
                if (from === null || from === i) return;
                const bars = [...navs];
                const [moved] = bars.splice(from, 1);
                // 「首页」固定首位：其它导航压到首页上 → 落到它之后（下标钳制 ≥1）
                if (bars[0] === "首页") i = Math.max(1, i);
                bars.splice(i, 0, moved);
                void useMenuStore.getState().reorderNavs(menu, bars);
              }}
              onDragEnd={() => { dragFrom.current = null; setDragTo(null); }}
              title={n === "首页" ? "点选打开；「首页」固定首位不可移动；右键 重命名/删除" : "点选或拖拽排序；右键 重命名/删除"}
            >
              {n}
            </button>
          ))}
          {ctx ? (
            <CtxMenu state={ctx} items={ctxItemsFor(ctx.target, { menuName: menu, navigate })} onClose={() => setCtx(null)} />
          ) : null}
        </div>
      ) : null}
      {loading ? (
        <div className="tool-canvas__empty"><Loader2 size={16} className="spin" /> 加载工具中…</div>
      ) : err ? (
        <div className="tool-canvas__empty tool-canvas__empty--err">加载失败：{err}</div>
      ) : tools.length === 0 ? (
        <div className="tool-canvas__empty">
          <div>「{menu} / {nav}」下暂无工具</div>
          <button
            className="tool-canvas__add"
            title={`在「${menu} / ${nav}」下添加工具`}
            onClick={() => openSettings({ tab: "tools", menu, nav })}
          >
            <Plus size={26} />
          </button>
          <div className="tool-canvas__hint">点击 ＋ 在「{menu} / {nav}」下添加工具</div>
        </div>
      ) : (
        <div className="tool-grid">
          {tools.map((t) => (
            <button
              key={t.工具名称}
              className={
                "tool-btn" +
                (t.active ? "" : " tool-btn--disabled") +
                ((t.启动方式 === "下载链接" || t.启动方式 === "链接打开") ? " tool-btn--link" : "")
              }
              title={`${t.启动方式} · ${t.工具路径}${!t.active ? "\n（路径不存在，已置灰）" : ""}`}
              disabled={!t.active || busy !== ""}
              onClick={() => void runTool(t.工具名称)}
            >
              {busy === t.工具名称 ? <Loader2 size={14} className="spin" /> : <Package size={14} />}
              <span className="tool-btn__name">{t.工具名称}</span>
              <span className="tool-btn__meta">[{t.启动方式}]</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
