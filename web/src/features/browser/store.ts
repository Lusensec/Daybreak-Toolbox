import { create } from "zustand";

/** 内置浏览器固定菜单名（路由 /browser/:menu/:name 的第一段） */
export const BROWSER_MENU = "浏览器";

/** 内置浏览器标签页 */
export interface BrowserTab {
  id: string;      // `${menu}::${name}`
  menu: string;
  name: string;
  url: string;
}

interface BrowserState {
  tabs: BrowserTab[];
  activeId: string;   // "" 表示无激活标签
  returnTo: string;   // 打开第一个标签之前的应用内路径（用于关闭最后一个标签后返回）
  openTab: (menu: string, name: string, url: string, returnTo?: string) => BrowserTab;
  closeTab: (id: string) => { remaining: number; nextId: string };
  setActive: (id: string) => void;
  /** 地址栏跳转：只改 URL，标签身份（menu/name）不变 */
  updateTabUrl: (id: string, url: string) => void;
}

/** 标签 id：菜单名不含连续双下划线，工具名在菜单内唯一 → 拼接不会冲突 */
function makeTabId(menu: string, name: string): string {
  return `${menu}::${name}`;
}

export const useBrowserStore = create<BrowserState>((set, get) => ({
  tabs: [],
  activeId: "",
  returnTo: "",

  openTab: (menu, name, url, returnTo) => {
    // 空参数会生成 id 为 "::" 的幽灵标签（顶栏入口指向 /browser/ 且无法关闭对应页面），直接拒绝
    if (!menu || !name || !url) throw new Error("浏览器标签缺少菜单、工具名或 URL");
    const st = get();
    const id = makeTabId(menu, name);
    const existing = st.tabs.find((t) => t.id === id);
    // 去重：已存在只激活，不重复添加
    if (existing) {
      if (st.activeId !== id) set({ activeId: id });
      return existing;
    }
    const tab: BrowserTab = { id, menu, name, url };
    // 首个标签：记录返回路径（传入优先；否则取当前路径，已在浏览器页则回首页）
    let nextReturnTo = st.returnTo;
    if (st.tabs.length === 0) {
      const fallback = window.location.pathname;
      nextReturnTo = returnTo ?? (fallback.startsWith("/browser") ? "/" : fallback);
    }
    set({ tabs: [...st.tabs, tab], activeId: id, returnTo: nextReturnTo });
    return tab;
  },

  closeTab: (id) => {
    const st = get();
    const idx = st.tabs.findIndex((t) => t.id === id);
    if (idx < 0) return { remaining: st.tabs.length, nextId: st.activeId };

    const tabs = st.tabs.filter((t) => t.id !== id);
    if (tabs.length === 0) {
      set({ tabs: [], activeId: "" });
      return { remaining: 0, nextId: "" };
    }
    // 关闭的不是激活标签 → 激活态不变
    if (st.activeId !== id) {
      set({ tabs });
      return { remaining: tabs.length, nextId: st.activeId };
    }
    // 关闭的是激活标签 → 优先后一个，否则前一个
    const nextId = (tabs[idx] ?? tabs[idx - 1]).id;
    set({ tabs, activeId: nextId });
    return { remaining: tabs.length, nextId };
  },

  setActive: (id) => set({ activeId: id }),

  updateTabUrl: (id, url) => {
    if (!id || !url) return;
    set((st) => ({ tabs: st.tabs.map((t) => (t.id === id ? { ...t, url } : t)) }));
  },
}));
