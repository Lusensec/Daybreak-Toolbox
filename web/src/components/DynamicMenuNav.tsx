import { useEffect, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router";
import { Pencil, Plus, Trash2, Eye, PanelLeft, Star, FolderOpen, Info, X } from "lucide-react";
import { useMenuStore } from "../features/menu/store";
import { sendCommand } from "../services/ws";
import { useToastStore } from "./toast";
import { useSettingsModal } from "../store/settingsModal";
import { promptOpen } from "./PromptDialog";
import { useWheelScrollHorizontal } from "../hooks/useWheelScroll";
import { useDetachStore } from "../features/floating/detachStore";
import { useDetachDrag } from "../features/floating/useDetachDrag";
import { detachToFloat, closeFloat } from "../features/floating/floatClient";
import { useBrowserStore, type BrowserTab } from "../features/browser/store";

/** 右键菜单目标：动态菜单栏 或 导航栏按钮 */
export interface CtxTarget {
  kind: "menu" | "nav";
  /** menu=菜单栏名；nav=导航栏名（所属菜单取 activeMenu） */
  name: string;
}
export interface CtxState {
  x: number;
  y: number;
  target: CtxTarget;
}

export interface CtxItem {
  label: string;
  /** sep=true 时渲染为分隔线（label/icon 被忽略） */
  sep?: boolean;
  icon?: "pencil" | "plus" | "trash" | "eye" | "panel-left" | "star" | "folder" | "info";
  danger?: boolean;
  run: () => void | Promise<void>;
}

/** 轻量自绘右键菜单：遮罩点击 / Esc 关闭，视口边缘自动收拢（固定菜单栏也复用） */
export function CtxMenu({ state, items, onClose }: { state: CtxState; items: CtxItem[]; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const W = 176;
  // 分隔线行高更矮（13px），普通项 34px——视口收拢计算按内容实际高度
  const H = items.reduce((h, it) => h + (it.sep ? 13 : 34), 0) + 12;
  const left = Math.max(4, Math.min(state.x, window.innerWidth - W - 8));
  const top = Math.max(4, Math.min(state.y, window.innerHeight - H - 8));
  return (
    <>
      <div className="ctx-backdrop" onMouseDown={onClose} />
      <div className="ctx-menu" style={{ left, top }} onMouseDown={(e) => e.stopPropagation()}>
        {items.map((it, i) =>
          it.sep ? (
            <div key={`sep-${i}`} className="ctx-menu__sep" />
          ) : (
            <button
              key={it.label}
              className={"ctx-menu__item" + (it.danger ? " danger" : "")}
              onClick={() => {
                void Promise.resolve(it.run()).finally(onClose);
              }}
            >
              {it.icon === "pencil" ? <Pencil size={13} /> : it.icon === "plus" ? <Plus size={13} /> : it.icon === "trash" ? <Trash2 size={13} /> : it.icon === "eye" ? <Eye size={13} /> : it.icon === "panel-left" ? <PanelLeft size={13} /> : it.icon === "star" ? <Star size={13} /> : it.icon === "folder" ? <FolderOpen size={13} /> : it.icon === "info" ? <Info size={13} /> : null}
              {it.label}
            </button>
          )
        )}
      </div>
    </>
  );
}

/** 生成「重命名 + 添加菜单栏 + 删除」三项（菜单 / 导航共用；重命名走全局 PromptDialog，
 *  添加菜单栏 → 工具箱设置「菜单栏管理」页；错误走全局 toast，menu.changed 自动刷新列表；
 * 子窗口导航行也复用，navigate 传主路由 —— 仅当主视图正停在该导航时路由跟随改名） */
export function ctxItemsFor(target: CtxTarget, opts: { menuName: string; navigate: (p: string) => void; omitUnpin?: boolean }): CtxItem[] {
  // 非组件上下文：直接读 toast store（useToast 是 hook，不能在此调用）
  const toast = {
    ok: (t: string) => useToastStore.getState().push("ok", t),
    err: (t: string) => useToastStore.getState().push("err", t),
  };
  const err = (e: unknown) => toast.err(`操作失败：${e instanceof Error ? e.message : String(e)}`);
  if (target.kind === "menu") {
    const m = target.name;
    return [
      {
        label: "重命名", icon: "pencil",
        run: async () => {
          const nn = await promptOpen(`重命名菜单栏「${m}」`, m);
          if (nn === null) return;
          const name = nn;
          try {
            await sendCommand("menu.rename", { name: m, new_name: name });
            // 若正在该菜单下 → 顶栏/路由同步跟到改名后（store 由 menu.changed 自动刷新）
            const st = useMenuStore.getState();
            if (st.activeMenu === m) {
              st.openToolCanvas(name, st.activeNav);
              opts.navigate(`/tools/${encodeURIComponent(name)}/${encodeURIComponent(st.activeNav)}`);
            }
            toast.ok(`菜单栏已重命名为「${name}」`);
          } catch (e) { err(e); }
        },
      },
      ...(opts.omitUnpin ? [] : [{
        label: "移到左侧栏", icon: "panel-left" as const,
        run: () => {
          // v2.2.0：顶栏「已上架」菜单移回左侧导航栏（顶栏只留首页 / 需要的菜单）。
          // 若正停在该菜单的工具画布 → 一并回首页（该菜单已离开顶栏工作区，
          // 留着画布却无导航行可切换会让人以为导航丢了）
          const st = useMenuStore.getState();
          const wasActive = st.activeMenu === m;
          st.unpinMenu(m);
          if (wasActive) opts.navigate("/");
          toast.ok(`菜单栏「${m}」已移回左侧导航栏`);
        },
      }]),
      {
        label: "添加菜单栏", icon: "plus",
        run: () => {
          // 打开工具箱设置并定位到「菜单栏管理」页（新增菜单栏行常显）
          useSettingsModal.getState().openModal({ tab: "menus" });
        },
      },
      {
        label: "删除菜单栏", icon: "trash", danger: true,
        run: async () => {
          if (!window.confirm(`删除菜单栏「${m}」？其下全部工具将从配置中移除（磁盘文件不删）`)) return;
          try {
            await sendCommand("menu.remove", { name: m });
            toast.ok(`菜单栏「${m}」已删除`);
          } catch (e) { err(e); }
        },
      },
    ];
  }
  const n = target.name;
  const menuName = opts.menuName;
  return [
    {
      label: "重命名", icon: "pencil",
      run: async () => {
        const nn = await promptOpen(`重命名导航栏「${n}」（菜单「${menuName}」）`, n);
        if (nn === null) return;
        const name = nn;
        try {
          await sendCommand("menu.rename_nav", { menu: menuName, nav: n, new_name: name });
          // 若路由正停在该导航 → 跟到改名后的导航（页面名同步）
          const st = useMenuStore.getState();
          if (st.activeMenu === menuName && st.activeNav === n) {
            st.openToolCanvas(menuName, name);
            opts.navigate(`/tools/${encodeURIComponent(menuName)}/${encodeURIComponent(name)}`);
          }
          toast.ok(`导航栏已重命名为「${name}」`);
        } catch (e) { err(e); }
      },
    },
    {
      label: "添加菜单栏", icon: "plus",
      run: () => {
        useSettingsModal.getState().openModal({ tab: "menus" });
      },
    },
    {
      label: "删除导航栏", icon: "trash", danger: true,
      run: async () => {
        if (!window.confirm(`删除导航栏「${n}」？该导航栏下的工具将一并删除，不可恢复`)) return;
        try {
          const r = await sendCommand("menu.remove_nav", { menu: menuName, nav: n });
          const removed = Number((r as { removed_tools?: number }).removed_tools ?? 0);
          toast.ok(removed ? `导航栏「${n}」已删除（连同 ${removed} 个工具）` : `导航栏「${n}」已删除`);
        } catch (e) { err(e); }
      },
    },
  ];
}

/**
 * 顶栏动态菜单（数据驱动，1:1 旧版 app.py 菜单栏 + reload_canvas）：
 *  - menus 来自 config/config.json（bridge menu.list，menu.changed 自动刷新）
 *  - 每个用户菜单是一个**可点击 + 可拖拽**按钮（useDetachDrag，pointer 事件）：
 *      点击展开 → 导航行显示为菜单栏正下方常驻第二行，并路由跳该菜单首导航；
 *      再点收起 → 只隐藏导航行，不跳路由；
 *      栏内拖动其它菜单上松手 → 在用户菜单间重排（menu.reorder 持久化 config.json）；
 *      **拖出顶栏区域松手 → 脱离为可移动子窗口**（浮层，纯 UI 状态，刷新收回）。
 *  - 固定的系统菜单（首页/AI对话/…）是 AppShell 里的独立按钮（同样可脱离），不在此组件内；
 *    此处**所有**动态菜单都可拖。
 *  - 菜单为空时整体隐藏（不占位）
 */
export function DynamicMenuNav({ barRef }: { barRef?: React.RefObject<HTMLElement | null> }) {
  const menus = useMenuStore((s) => s.menus);
  const activeMenu = useMenuStore((s) => s.activeMenu);
  const pinned = useMenuStore((s) => s.pinned);
  const navigate = useNavigate();
  const [ctx, setCtx] = useState<CtxState | null>(null);

  // v2.2.0：顶栏只渲染「已上架」的菜单（默认空 → 顶栏仅剩固定菜单「首页」），
  // 全部用户菜单在左侧导航栏；点左侧菜单/导航 → 该菜单上架到顶栏并展开其导航行。
  // 菜单栏展示参数（config.json menu_visible）：0 = 顶栏不渲染该菜单栏（即便已上架）。
  const visibleMenus = menus.filter((m) => (m.menu_visible ?? 1) !== 0 && pinned.includes(m.name));

  if (visibleMenus.length === 0) return null;

  function clickMenu(m: { name: string; navigation_bar_name: string[] }) {
    const st = useMenuStore.getState();
    if (st.activeMenu === m.name) {
      st.toggleMenu(m.name); // 已激活再点 → 收起导航行（不跳路由）
      return;
    }
    const firstNav = m.navigation_bar_name[0] ?? "首页";
    st.openToolCanvas(m.name, firstNav);
    navigate(`/tools/${encodeURIComponent(m.name)}/${encodeURIComponent(firstNav)}`);
  }

  /** 栏内拖放重排：moveFrom→moveTo（与导航栏 onDrop 同款插缝算法：
   *  移除后按目标「原始下标」插入 → 右拖落目标之后、左拖落目标之前，
   *  拖到第一个按钮上即可排到最前；重排序列含隐藏项，后端要求全量排列） */
  function reorderMenus(moveFrom: string, moveTo: string) {
    const allNames = menus.map((m) => m.name);
    const fromFull = allNames.indexOf(moveFrom);
    const toFull = allNames.indexOf(moveTo);
    if (fromFull < 0 || toFull < 0 || fromFull === toFull) return;
    const moved = allNames.splice(fromFull, 1)[0];
    allNames.splice(toFull, 0, moved);
    void useMenuStore.getState().reorderMenus(allNames);
  }

  return (
    <div className="dynamic-menus">
      <span className="dynamic-menus__sep" />
      {visibleMenus.map((m) => (
        <DynamicMenuButton
          key={m.name}
          m={m}
          active={activeMenu === m.name}
          barRef={barRef}
          onClick={clickMenu}
          onInBarDrop={(t) => reorderMenus(m.name, t)}
          onCtx={(x, y) => setCtx({ x, y, target: { kind: "menu", name: m.name } })}
        />
      ))}
      <span className="dynamic-menus__sep" />
      {ctx ? (
        <CtxMenu state={ctx} items={ctxItemsFor(ctx.target, { menuName: activeMenu, navigate })} onClose={() => setCtx(null)} />
      ) : null}
    </div>
  );
}

/** 单个用户菜单按钮：点击展开/收起 + 右键 重命名/删除 + 拖拽（栏内重排 / 拖出脱离为子窗口）
 *
 *  v2.2.2：悬停时右侧浮现「×」按钮 —— 点击即把该菜单**移回左侧导航栏**
 *  （等价于右键菜单里的「移到左侧栏」，此处给出更直观的入口）。
 *  × 按钮是独立元素（不嵌在菜单按钮内），避免与按钮自身的
 *  pointerdown 拖拽手势（脱离为子窗口）互相干扰。 */
function DynamicMenuButton({ m, active, barRef, onClick, onInBarDrop, onCtx }: {
  m: { name: string; menu_color?: string; navigation_bar_name: string[] };
  active: boolean;
  barRef?: React.RefObject<HTMLElement | null>;
  onClick: (m: { name: string; navigation_bar_name: string[] }) => void;
  onInBarDrop: (targetName: string) => void;
  onCtx: (x: number, y: number) => void;
}) {
  const { startDrag, suppressClick, ghost, hoverMe } = useDetachDrag({
    name: m.name,
    key: m.name,
    label: m.name,
    color: m.menu_color,
    reorderable: true,
    onInBarDrop,
    barRef: barRef ?? ({ current: null } as React.RefObject<HTMLElement | null>),
    // v2.3.2：拖出顶栏 → 独立原生窗口（不可用时 floatClient 自动回退 HTML 浮层）
    detach: (x, y) => {
      const nav = m.navigation_bar_name[0] ?? "首页";
      void detachToFloat({ key: m.name, label: m.name, kind: "menu", menu: m.name, nav, x, y });
    },
  });
  const detached = useDetachStore((s) => m.name in s.detached);
  const navigate = useNavigate();

  /** ×：把该菜单从顶栏收回左侧栏（与右键「移到左侧栏」同语义） */
  function moveBackToSide() {
    const st = useMenuStore.getState();
    const wasActive = st.activeMenu === m.name;
    st.unpinMenu(m.name);
    // 该菜单若正是当前展开的 → 顶栏已无它，导航行随之收起 → 路由回首页
    if (wasActive) navigate("/");
    useToastStore.getState().push("ok", `菜单栏「${m.name}」已移回左侧导航栏`);
  }

  return (
    <>
      <span className="dynamic-menu__wrap" data-detach-btn={m.name}>
        <button
          className={
            "dynamic-menu__btn" +
            (active ? " active" : "") +
            (detached ? " dynamic-menu__btn--detached" : "") +
            (hoverMe ? " dynamic-menu__btn--drop-target" : "")
          }
          data-detach-btn={m.name}
          onPointerDown={startDrag}
          onClick={(e) => {
            if (suppressClick()) { e.preventDefault(); return; }
            if (detached) { e.preventDefault(); closeFloat(m.name); return; }
            onClick(m);
          }}
          onContextMenu={(e) => {
            e.preventDefault();
            onCtx(e.clientX, e.clientY);
          }}
          title={
            detached
              ? `「${m.name}」已脱离为子窗口，点击收回菜单栏`
              : `点击${active ? "收起" : "显示"}「${m.name}」；拖动到其它菜单上重排；拖出顶栏脱离为子窗口；右键 重命名/删除`
          }
        >
          <span className="dynamic-menu__dot" style={{ background: m.menu_color || "#2980b9" }} />
          {m.name}
          {detached ? <span className="nav-link__detached-tag">已脱离</span> : null}
        </button>
        {/* v2.2.2：悬停时右侧浮现 × —— 收回左侧栏。
            「已脱离」态下按钮内有角标、右侧无余量，× 不显示（此时点击是收回子窗口）。 */}
        {detached ? null : (
          <button
            className="dynamic-menu__close"
            title="移回左侧导航栏"
            aria-label={`将 ${m.name} 移回左侧导航栏`}
            onPointerDown={(e) => { e.stopPropagation(); e.preventDefault(); }}
            onClick={(e) => { e.stopPropagation(); moveBackToSide(); }}
          >
            <X size={12} />
          </button>
        )}
      </span>
      {ghost}
    </>
  );
}

/**
 * 导航栏行（菜单栏正下方，常驻第二行，1:1 旧版 create_Navigation_Bar 位置）：
 *  - 显示当前 activeMenu 的 navigation_bar_name 按钮组，**可拖拽排序**（menu.reorder_nav）
 *  - 点导航 → 该导航的工具画布页；当前导航高亮
 *  - 没有激活菜单时整行隐藏（SSH 主机下拉框在终端管理页工具栏内）
 */
export function NavBarRow() {
  const menus = useMenuStore((s) => s.menus);
  const activeMenu = useMenuStore((s) => s.activeMenu);
  const navigate = useNavigate();
  const loc = useLocation();
  const rowRef = useRef<HTMLDivElement>(null);
  const [ctx, setCtx] = useState<CtxState | null>(null);

  const menu = menus.find((m) => m.name === activeMenu);
  const enabled = !!(menu && menu.navigation_bar_name.length > 0);
  // 内置浏览器路由下，导航行改为「浏览器标签行」（不受当前激活菜单约束）。
  // hook 必须无条件调用：先订阅标签列表，再统一决定滚动监听与渲染分支。
  const isBrowserRoute = loc.pathname.startsWith("/browser");
  const browserTabs = useBrowserStore((s) => s.tabs);
  useWheelScrollHorizontal(rowRef, isBrowserRoute || enabled);

  if (isBrowserRoute) return <BrowserTabsRow rowRef={rowRef} tabs={browserTabs} />;
  if (!enabled) return null;

  function go(nav: string) {
    useMenuStore.getState().openToolCanvas(menu!.name, nav);
    navigate(`/tools/${encodeURIComponent(menu!.name)}/${encodeURIComponent(nav)}`);
  }

  /** 栏内拖放重排（v2.3.2：从 HTML5 DnD 改为与顶栏一致的 pointer 拖拽；
   *  targetKey = `菜单::导航`，插缝算法与旧 onDrop 完全一致） */
  function reorderNavs(moveNav: string, targetKey: string) {
    const prefix = `${menu!.name}::`;
    const targetNav = targetKey.startsWith(prefix) ? targetKey.slice(prefix.length) : targetKey;
    const bars = [...menu!.navigation_bar_name];
    const from = bars.indexOf(moveNav);
    const to = bars.indexOf(targetNav);
    if (from < 0 || to < 0 || from === to) return;
    const [moved] = bars.splice(from, 1);
    // 「首页」固定首位：其它导航压到首页上松手 → 落到首页之后（下标钳制 ≥1）
    const insertAt = bars[0] === "首页" ? Math.max(1, to) : to;
    bars.splice(insertAt, 0, moved);
    void useMenuStore.getState().reorderNavs(menu!.name, bars);
  }

  // 在工具画布页之外的路由，当前导航不高亮
  const canvasNav = loc.pathname.startsWith("/tools/") ? decodeURIComponent(loc.pathname.split("/").pop() || "") : "";

  return (
    <div className="nav-bar-row" ref={rowRef}>
      {menu!.navigation_bar_name.map((n) => (
        <NavButton
          key={n}
          menu={menu!.name}
          nav={n}
          active={canvasNav === n}
          barRef={rowRef}
          onGo={go}
          onReorder={(targetKey) => reorderNavs(n, targetKey)}
          onCtx={(x, y) => setCtx({ x, y, target: { kind: "nav", name: n } })}
        />
      ))}
      {ctx ? (
        <CtxMenu
          state={ctx}
          items={ctxItemsFor(ctx.target, { menuName: menu!.name, navigate })}
          onClose={() => setCtx(null)}
        />
      ) : null}
    </div>
  );
}

/** 导航栏按钮（v2.3.2）：pointer 拖拽统一处理「栏内重排 / 拖出脱离为原生子窗口」，
 *  与顶栏菜单按钮共用 useDetachDrag；点击/右键行为保持不变。 */
function NavButton({ menu, nav, active, barRef, onGo, onReorder, onCtx }: {
  menu: string;
  nav: string;
  active: boolean;
  barRef: React.RefObject<HTMLElement | null>;
  onGo: (nav: string) => void;
  onReorder: (targetKey: string) => void;
  onCtx: (x: number, y: number) => void;
}) {
  const key = `${menu}::${nav}`;
  const label = `${menu} · ${nav}`;
  const detached = useDetachStore((s) => key in s.detached);
  const { startDrag, suppressClick, ghost, hoverMe } = useDetachDrag({
    name: nav,
    key,
    label,
    barRef,
    reorderable: true,
    onInBarDrop: onReorder,
    detach: (x, y) => {
      void detachToFloat({ key, label, kind: "nav", menu, nav, x, y });
    },
  });

  return (
    <>
      <button
        className={
          "nav-bar-row__btn" +
          (active ? " active" : "") +
          (detached ? " nav-bar-row__btn--detached" : "") +
          (hoverMe ? " drop-target" : "")
        }
        data-detach-btn={key}
        draggable={false}
        onDragStart={(e) => e.preventDefault()}
        onPointerDown={startDrag}
        onClick={(e) => {
          if (suppressClick()) { e.preventDefault(); return; }
          if (detached) { e.preventDefault(); closeFloat(key); return; }
          onGo(nav);
        }}
        onContextMenu={(e) => {
          e.preventDefault();
          onCtx(e.clientX, e.clientY);
        }}
        title={
          detached
            ? `「${label}」已脱离为子窗口，点击收回导航栏`
            : "点选打开；拖动排序；拖出导航栏脱离为子窗口；右键 重命名/删除"
        }
      >
        {nav}
        {detached ? <span className="nav-link__detached-tag">已脱离</span> : null}
      </button>
      {ghost}
    </>
  );
}

/** 解析 /browser/:menu/:name（react-router 路由参数已解码，这里按段再解一次以兼容直接拼接的路径） */
function parseBrowserRoute(pathname: string): { menu: string; name: string } {
  const seg = pathname.split("/");
  if (seg[1] !== "browser") return { menu: "", name: "" };
  return {
    menu: decodeURIComponent(seg[2] ?? ""),
    name: decodeURIComponent(seg[3] ?? ""),
  };
}

/** 标签对应的路由（编码方式与 launch.ts / AppShell 顶栏入口保持一致） */
function browserTabPath(tab: BrowserTab): string {
  return `/browser/${encodeURIComponent(tab.menu)}/${encodeURIComponent(tab.name)}`;
}

/** 关闭最后一个标签返回工具画布时恢复激活菜单。
 *  AppShell 在离开 /tools 路由时会 clearActive，仅靠 navigate 回去会出现
 *  「画布还在、导航行却消失」；这里按来源路径把菜单重新上架并定位导航。 */
function restoreToolCanvasState(path: string) {
  const m = /^\/tools\/([^/]+)(?:\/([^/]+))?/.exec(path);
  if (!m) return;
  try {
    const menuName = decodeURIComponent(m[1]);
    const nav = m[2] ? decodeURIComponent(m[2]) : "首页";
    const st = useMenuStore.getState();
    if (!st.menus.some((x) => x.name === menuName)) return;
    st.pinMenu(menuName);
    st.openToolCanvas(menuName, nav);
  } catch { /* 路径解码异常则不恢复，退回首页 */ }
}

/**
 * 内置浏览器标签行（/browser/* 路由下替代普通导航行）：
 *  - 每个已打开标签一个按钮，当前路由对应标签高亮（按 menu/name 比对，不依赖 store 顺序）；
 *  - 悬停时右侧浮现 × 关闭；关闭后按 closeTab 返回的 nextId 跳转，
 *    最后一个标签关闭则返回打开浏览器前的应用内路径（returnTo）。
 *  - 标签列表由 NavBarRow 订阅后传入，避免同一状态重复订阅。
 */
function BrowserTabsRow({ rowRef, tabs }: {
  rowRef: React.RefObject<HTMLDivElement | null>;
  tabs: BrowserTab[];
}) {
  const navigate = useNavigate();
  const loc = useLocation();
  const route = parseBrowserRoute(loc.pathname);

  function openTab(tab: BrowserTab) {
    useBrowserStore.getState().setActive(tab.id);
    navigate(browserTabPath(tab));
  }

  function closeTab(tab: BrowserTab) {
    // 先记住关闭前是否激活：closeTab 会改写 activeId，关闭后再判断就晚了
    const wasActive = tab.menu === route.menu && tab.name === route.name;
    const st = useBrowserStore.getState();
    const r = st.closeTab(tab.id);
    if (r.remaining === 0) {
      restoreToolCanvasState(st.returnTo);
      navigate(st.returnTo || "/");
      return;
    }
    if (!wasActive) return;
    // closeTab 已把激活态切到 nextId（后一个优先，否则前一个）→ 路由跟过去
    const next = useBrowserStore.getState().tabs.find((t) => t.id === r.nextId);
    if (next) navigate(browserTabPath(next));
  }

  return (
    <div className="nav-bar-row" ref={rowRef}>
      <span className="nav-bar-row__label">浏览器</span>
      {tabs.map((tab) => {
        const active = tab.menu === route.menu && tab.name === route.name;
        return (
          <BrowserTabButton
            key={tab.id}
            tab={tab}
            active={active}
            barRef={rowRef}
            onOpen={() => openTab(tab)}
            onClose={() => closeTab(tab)}
          />
        );
      })}
    </div>
  );
}

/** 浏览器标签（v2.3.2）：点击切换；拖出标签栏 → 独立子窗口（窗口内嵌原生 WebView2 显示该网页）。 */
function BrowserTabButton({ tab, active, barRef, onOpen, onClose }: {
  tab: BrowserTab;
  active: boolean;
  barRef: React.RefObject<HTMLElement | null>;
  onOpen: () => void;
  onClose: () => void;
}) {
  const key = `browser::${tab.id}`;
  const detached = useDetachStore((s) => key in s.detached);
  const { startDrag, suppressClick, ghost, hoverMe } = useDetachDrag({
    name: tab.name,
    key,
    label: tab.name,
    barRef,
    reorderable: false,
    detach: (x, y) => {
      void detachToFloat({
        key,
        label: tab.name,
        kind: "browser",
        menu: tab.menu,
        nav: tab.name,
        url: tab.url,
        x,
        y,
      });
    },
  });

  return (
    <span
      className={
        "browser-tab" +
        (active ? " is-active" : "") +
        (detached ? " browser-tab--detached" : "")
      }
    >
      <button
        className={"nav-bar-row__btn" + (active ? " active" : "") + (hoverMe ? " drop-target" : "")}
        data-detach-btn={key}
        title={`${tab.url}\n拖动可脱离为子窗口`}
        onPointerDown={startDrag}
        onClick={(e) => {
          if (suppressClick()) { e.preventDefault(); return; }
          if (detached) { e.preventDefault(); closeFloat(key); return; }
          onOpen();
        }}
      >
        {tab.name}
        {detached ? <span className="nav-link__detached-tag">已脱离</span> : null}
      </button>
      <button
        className="browser-tab__close"
        title="关闭标签"
        aria-label={`关闭标签 ${tab.name}`}
        onClick={onClose}
      >
        <X size={11} />
      </button>
      {ghost}
    </span>
  );
}
