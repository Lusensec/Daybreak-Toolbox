import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router";
import {
  ChevronsDownUp, ChevronsUpDown, Folder, FolderOpen,
  PanelLeftClose, PanelLeftOpen, Pin, Plus, Wrench,
} from "lucide-react";
import { useMenuStore } from "../features/menu/store";
import type { MenuInfo } from "../features/menu/store";
import { useSettingsModal } from "../store/settingsModal";
import "./SideNav.css";

/** v2.2.0 左侧导航栏（文件夹式）：
 *  - 全部用户菜单栏常驻左侧（像文件夹那样），菜单下可展开/收缩其导航栏列表；
 *  - 点菜单 → 该菜单**上架到顶栏**（pin）并展开顶栏导航行，同时跳到首个导航；
 *  - 点导航 → 上架所属菜单并直接定位到该导航；
 *  - 整栏可折叠为图标条（状态存 localStorage，刷新保持）；
 *  - 「菜单栏展示」= 0 的菜单不在此列出（与顶栏同一份可见性语义，设置页可恢复）。
 *  顶栏默认只剩固定菜单「首页」，用户菜单按需上架 → 顶栏不再被菜单挤满。
 */

const COLLAPSE_KEY = "daybreak.sidebar.collapsed";
const EXPAND_KEY = "daybreak.sidebar.expanded";
/** v2.2.1：侧栏宽度（可拖右边缘拉伸）——持久化在 localStorage */
const WIDTH_KEY = "daybreak.sidebar.width";
const WIDTH_MIN = 180;
const WIDTH_MAX = 480;

function loadCollapsed(): boolean {
  try { return localStorage.getItem(COLLAPSE_KEY) === "1"; } catch { return false; }
}
function loadExpanded(): Record<string, boolean> {
  try {
    const v = JSON.parse(localStorage.getItem(EXPAND_KEY) || "{}");
    return v && typeof v === "object" ? (v as Record<string, boolean>) : {};
  } catch { return {}; }
}
function loadWidth(): number {
  try {
    const n = Number(localStorage.getItem(WIDTH_KEY));
    if (Number.isFinite(n) && n >= WIDTH_MIN && n <= WIDTH_MAX) return n;
  } catch { /* ignore */ }
  return 252;
}
function save(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* 隐私模式忽略 */ }
}

export function SideNav() {
  const menus = useMenuStore((s) => s.menus);
  const activeMenu = useMenuStore((s) => s.activeMenu);
  const activeNav = useMenuStore((s) => s.activeNav);
  const pinned = useMenuStore((s) => s.pinned);
  const navigate = useNavigate();
  const openSettings = useSettingsModal((s) => s.openModal);

  const [collapsed, setCollapsed] = useState(loadCollapsed);
  const [expanded, setExpanded] = useState<Record<string, boolean>>(loadExpanded);
  // v2.2.1：侧栏宽度（拖右边缘拉伸）
  const [width, setWidth] = useState(loadWidth);
  const resizingRef = useRef(false);

  const visible = useMemo(() => menus.filter((m) => (m.menu_visible ?? 1) !== 0), [menus]);

  // 折叠态持久化
  useEffect(() => { save(COLLAPSE_KEY, collapsed ? "1" : "0"); }, [collapsed]);
  // 展开态持久化
  useEffect(() => { save(EXPAND_KEY, JSON.stringify(expanded)); }, [expanded]);
  // 宽度持久化（折叠态不写，展开时恢复用户设定值）
  useEffect(() => { if (!collapsed) save(WIDTH_KEY, String(width)); }, [collapsed, width]);
  // 顶栏激活的菜单 → 左侧自动展开（两处状态保持一致，便于对照）
  useEffect(() => {
    if (!activeMenu) return;
    setExpanded((prev) => (prev[activeMenu] ? prev : { ...prev, [activeMenu]: true }));
  }, [activeMenu]);

  /** v2.2.1：拖右边缘改宽度。
   *  用 window 级 mousemove/mouseup 监听（而非 React onMouseMove）——
   *  指针拖出侧栏范围时事件仍能收到；mouseup 丢失时靠 blur/pointercancel 兜底拆除。 */
  function startResize(e: React.MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    if (collapsed) return;
    const startX = e.screenX;
    const startW = width;
    resizingRef.current = true;

    const onMove = (ev: MouseEvent) => {
      if (!resizingRef.current) return;
      const next = Math.round(Math.min(WIDTH_MAX, Math.max(WIDTH_MIN, startW + (ev.screenX - startX))));
      setWidth(next);
    };
    const teardown = () => {
      resizingRef.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", teardown);
      window.removeEventListener("pointercancel", teardown);
      window.removeEventListener("blur", teardown);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", teardown);
    window.addEventListener("pointercancel", teardown);
    window.addEventListener("blur", teardown);
  }

  /** 打开菜单：上架到顶栏 + 展开导航行 + 跳到首个导航 */
  function openMenu(m: MenuInfo, nav?: string) {
    const st = useMenuStore.getState();
    st.pinMenu(m.name);
    const target = nav ?? m.navigation_bar_name[0] ?? "首页";
    st.openToolCanvas(m.name, target);
    setExpanded((prev) => (prev[m.name] ? prev : { ...prev, [m.name]: true }));
    navigate(`/tools/${encodeURIComponent(m.name)}/${encodeURIComponent(target)}`);
  }

  /** v2.2.3：取消独立下拉箭头——整行即为开关。
   *  首次点（收缩态）→ 展开导航 + 上架顶栏 + 跳转首个导航；
   *  再次点（展开态）→ 只收缩导航，不再跳页，方便反复开合。 */
  function onMenuClick(m: MenuInfo) {
    if (expanded[m.name]) {
      setExpanded((prev) => ({ ...prev, [m.name]: false }));
      return;
    }
    openMenu(m);
  }

  const allExpanded = visible.length > 0 && visible.every((m) => expanded[m.name]);

  return (
    <aside
      className="side-nav"
      data-collapsed={collapsed ? "1" : "0"}
      style={collapsed ? undefined : { width: `${width}px` }}
    >
      <div className="side-nav__head">
        {collapsed ? null : (
          <span className="side-nav__title">
            <Folder size={13} /> 我的菜单
          </span>
        )}
        <div className="side-nav__head-actions">
          {collapsed ? null : (
            <button
              className="side-nav__icon-btn"
              title={allExpanded ? "全部收缩" : "全部展开"}
              onClick={() =>
                setExpanded(
                  allExpanded
                    ? {}
                    : Object.fromEntries(visible.map((m) => [m.name, true])),
                )
              }
            >
              {allExpanded ? <ChevronsDownUp size={14} /> : <ChevronsUpDown size={14} />}
            </button>
          )}
          <button
            className="side-nav__icon-btn"
            title={collapsed ? "展开导航栏" : "收起导航栏"}
            onClick={() => setCollapsed((v) => !v)}
          >
            {collapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
          </button>
        </div>
      </div>

      <div className="side-nav__list">
        {visible.length === 0 ? (
          collapsed ? null : (
            <div className="side-nav__empty">
              暂无菜单栏
              <button className="side-nav__empty-btn" onClick={() => openSettings({ tab: "menus" })}>
                <Plus size={12} /> 新建
              </button>
            </div>
          )
        ) : (
          visible.map((m) => {
            const isActive = activeMenu === m.name;
            const isOpen = !!expanded[m.name];
            const isPinned = pinned.includes(m.name);
            return (
              <div className={"side-nav__menu" + (isActive ? " is-active" : "")} key={m.name}>
                <div className="side-nav__row">
                  <button
                    className={"side-nav__menu-btn" + (isActive ? " is-active" : "")}
                    title={
                      collapsed
                        ? `${m.name}（${m.tool_count} 个工具）`
                        : `${m.name}\n点击：${isOpen ? "收缩" : "展开"}导航${isOpen ? "" : "并上架到顶栏"}\n导航：${m.navigation_bar_name.join(" / ") || "无"}`
                    }
                    onClick={() => onMenuClick(m)}
                  >
                    {isOpen && !collapsed ? <FolderOpen size={14} className="side-nav__folder" /> : <Folder size={14} className="side-nav__folder" />}
                    <span className="side-nav__dot" style={{ background: m.menu_color || "#2980b9" }} />
                    {collapsed ? null : (
                      <>
                        <span className="side-nav__name">{m.name}</span>
                        {isPinned ? <Pin size={11} className="side-nav__pin" aria-label="已在顶栏" /> : null}
                        <span className="side-nav__count" title={`${m.navigation_bar_name.length} 个导航 · ${m.tool_count} 个工具`}>
                          {m.tool_count}
                        </span>
                      </>
                    )}
                  </button>
                </div>

                {/* 导航栏列表：像文件夹那样逐层展开（折叠整栏时一并隐藏） */}
                {!collapsed && isOpen ? (
                  <div className="side-nav__navs">
                    {m.navigation_bar_name.length === 0 ? (
                      <div className="side-nav__nav-empty">暂无导航栏</div>
                    ) : (
                      m.navigation_bar_name.map((n) => (
                        <button
                          key={n}
                          className={"side-nav__nav" + (isActive && activeNav === n ? " is-active" : "")}
                          title={`打开「${m.name} / ${n}」`}
                          onClick={() => openMenu(m, n)}
                        >
                          <span className="side-nav__nav-bar" />
                          {n}
                        </button>
                      ))
                    )}
                  </div>
                ) : null}
              </div>
            );
          })
        )}
      </div>

      <div className="side-nav__foot">
        <button
          className="side-nav__foot-btn"
          title="打开工具箱设置（菜单栏 / 导航栏 / 工具管理）"
          onClick={() => openSettings({ tab: "menus" })}
        >
          {collapsed ? <Plus size={14} /> : <><Wrench size={13} /> 管理菜单</>}
        </button>
      </div>

      {/* v2.2.1：右边缘拖拽手柄 —— 左右拉伸侧栏宽度（180~480px，持久化）。
          折叠态不显示（此时宽度固定 52px）。 */}
      {collapsed ? null : (
        <div
          className="side-nav__resizer"
          title="拖动调整侧栏宽度"
          onMouseDown={startResize}
        />
      )}
    </aside>
  );
}
