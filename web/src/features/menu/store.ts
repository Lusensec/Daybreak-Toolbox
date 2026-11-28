import { create } from "zustand";
import { sendCommand, subscribeEvent, useConnStore } from "../../services/ws";

/** 一个菜单栏（与 bridge menu.list 对齐） */
export interface MenuInfo {
  name: string;
  menu_path: string;
  menu_color: string;
  navigation_bar_name: string[];
  tool_count: number;
  /** 显隐参数（config.json menu_visible）：1 显示 / 0 隐藏，缺省 1 */
  menu_visible: number;
}

/** 固定菜单栏（首页/AI 对话/…）显隐表：{名称: 1|0}，缺省视为 1 */
export type FixedVisible = Record<string, number>;

/** 工具画布页选中态：当前菜单 + 导航（导航空则默认首页） */
interface MenuStore {
  menus: MenuInfo[];
  /** 菜单 → 工具列表（menu.list_tools 顺序：导航序 × 工具序；工具快捷键默认编号的依据） */
  tools: Record<string, { nav: string; name: string }[]>;
  fixedVisible: FixedVisible;
  loading: boolean;
  loaded: boolean;
  activeMenu: string;
  activeNav: string;
  /** v2.2.0：顶栏展示的菜单名列表（「已上架」）。
   *  默认空 → 顶栏只剩固定菜单「首页」，全部用户菜单在左侧导航栏；
   *  点左侧菜单/导航时该菜单被 pin 到顶栏并展开导航行；顶栏右键可移回左侧。
   *  UI 状态（非数据），persist 到 localStorage。 */
  pinned: string[];
  refresh: () => Promise<void>;
  openToolCanvas: (menu: string, nav?: string) => void;
  toggleMenu: (name: string) => void;   // 点顶栏动态菜单：显示/隐藏其导航行
  clearActive: () => void;             // 点固定功能导航时隐藏导航行
  pinMenu: (name: string) => void;     // 菜单上架到顶栏
  unpinMenu: (name: string) => void;   // 菜单移回左侧栏
  reorderMenus: (order: string[]) => Promise<boolean>;
  reorderNavs: (menu: string, order: string[]) => Promise<boolean>;
}

/** 顶栏「已上架」菜单名单（v2.2.0）：localStorage 持久化，刷新后保持 */
const PINNED_KEY = "daybreak.topbar.pinned";

function loadPinned(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(PINNED_KEY) || "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function savePinned(list: string[]) {
  try { localStorage.setItem(PINNED_KEY, JSON.stringify(list)); } catch { /* 隐私模式忽略 */ }
}

/** 固定菜单栏是否显示（缺省 1） */
export function isFixedVisible(fv: FixedVisible, name: string): boolean {
  return (fv[name] ?? 1) !== 0;
}

export const useMenuStore = create<MenuStore>((set, get) => ({
  menus: [],
  tools: {},
  fixedVisible: {},
  loading: false,
  loaded: false,
  activeMenu: "",
  activeNav: "首页",
  pinned: loadPinned(),

  refresh: async () => {
    if (get().loading) return;
    set({ loading: true });
    try {
      const r = await sendCommand("menu.list", {});
      const menus = (r.menus ?? []) as MenuInfo[];
      set({
        menus,
        fixedVisible: (r.fixed_visible ?? {}) as FixedVisible,
        loading: false,
        loaded: true,
      });
      // 工具列表（逐菜单 menu.list_tools）：工具快捷键默认编号 = 菜单序 × 列表序
      const toolMaps = await Promise.all(menus.map(async (m) => {
        try {
          const r2 = await sendCommand("menu.list_tools", { menu: m.name });
          const list = (r2.tools ?? []) as { nav?: string; 工具名称: string }[];
          return [m.name, list.map((t) => ({ nav: String(t.nav ?? "首页"), name: t.工具名称 }))] as const;
        } catch {
          return [m.name, [] as { nav: string; name: string }[]] as const;
        }
      }));
      set({ tools: Object.fromEntries(toolMaps) });
      // v2.2.0：清理已不存在的「已上架」菜单（被删除/改名 → 顶栏不残留幽灵按钮）
      const pinned = get().pinned.filter((n) => menus.some((m) => m.name === n));
      if (pinned.length !== get().pinned.length) {
        set({ pinned });
        savePinned(pinned);
      }
      // 保持当前 activeMenu 有效；否则清空
      const cur = get().activeMenu;
      if (cur && !menus.some((m) => m.name === cur)) {
        set({ activeMenu: "", activeNav: "首页" });
      }
    } catch {
      set({ loading: false });
    }
  },

  openToolCanvas: (menu, nav = "首页") => set({ activeMenu: menu, activeNav: nav }),

  toggleMenu: (name) => {
    const st = get();
    if (st.activeMenu === name) {
      set({ activeMenu: "", activeNav: "首页" });
    } else {
      set({
        activeMenu: name,
        activeNav: st.menus.find((m) => m.name === name)?.navigation_bar_name[0] ?? "首页",
      });
    }
  },

  clearActive: () => set({ activeMenu: "", activeNav: "首页" }),

  // v2.2.0：顶栏「已上架」菜单（左侧栏点击 → 回归顶栏并展开导航）
  pinMenu: (name) => {
    if (!name) return;
    const cur = get().pinned;
    if (cur.includes(name)) return;
    const next = [...cur, name];
    set({ pinned: next });
    savePinned(next);
  },

  unpinMenu: (name) => {
    const cur = get().pinned;
    if (!cur.includes(name)) return;
    const next = cur.filter((n) => n !== name);
    set({ pinned: next });
    savePinned(next);
    // 移回左侧后顶栏不再有该菜单 → 导航行随之收起
    if (get().activeMenu === name) set({ activeMenu: "", activeNav: "首页" });
  },

  reorderMenus: async (order) => {
    const st = get();
    // 乐观更新：仅对已存在的菜单改名排序（保持顺序为新 order 中实际存在的项）
    const byName = new Map(st.menus.map((m) => [m.name, m]));
    const next = order.map((n) => byName.get(n)).filter(Boolean) as MenuInfo[];
    if (next.length !== st.menus.length) return false; // 序列不一致（未刷新），交由后端报错
    set({ menus: next });
    try {
      await sendCommand("menu.reorder", { order });
      return true;
    } catch {
      await st.refresh(); // 回滚：重新拉取真实顺序
      return false;
    }
  },

  reorderNavs: async (menu, order) => {
    const st = get();
    const cur = st.menus.find((m) => m.name === menu);
    if (!cur) return false;
    const setOfCur = new Set(cur.navigation_bar_name);
    if (order.some((n) => !setOfCur.has(n)) || order.length !== cur.navigation_bar_name.length) {
      return false;
    }
    // 乐观更新该菜单导航序
    set({
      menus: st.menus.map((m) =>
        m.name === menu ? { ...m, navigation_bar_name: [...order] } : m),
    });
    try {
      await sendCommand("menu.reorder_nav", { menu, order });
      return true;
    } catch {
      await st.refresh();
      return false;
    }
  },
}));

// 订阅 menu.changed 自动刷新（设置模态框增删菜单/工具后顶栏同步）
let _subscribed = false;
export function bindMenuEvents() {
  if (_subscribed) return;
  _subscribed = true;
  subscribeEvent("menu.changed", () => {
    void useMenuStore.getState().refresh();
  });
  // 桥接状态：首次上线 / 断线重连成功时重载菜单
  // （修复根因：初始 refresh 时 WS 未连上，sendCommand 抛 "ws not connected" 后无重试，
  //   useMenuStore.menus 一直为空 → DynamicMenuNav 整体不渲染）
  useConnStore.subscribe((state, prev) => {
    if (state.status === "online" && prev.status !== "online") {
      void useMenuStore.getState().refresh();
    }
  });
  void useMenuStore.getState().refresh();
}
