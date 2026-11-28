import { useEffect } from "react";
import { useNavigate } from "react-router";
import { useMenuStore } from "../menu/store";
import { FIXED_MENUS } from "../menu/fixedMenus";
import { launchTool } from "../browser/launch";
import { useToastStore } from "../../components/toast";
import { useSettingsModal } from "../../store/settingsModal";
import { useShortcutsStore } from "./store";
import { allSlots, effectiveCombo, eventCombo, SLOT_PANEL, toolDefaults } from "./shortcuts";

/** 系统固定菜单栏 → 路由（与 App.tsx 一致）。v2.1.3：固定菜单只剩「首页」，
 *  其余固定功能面板（AI 对话 / 终端管理 / 编解码 / 汉英翻译 / 临时笔记）已移除。 */
const FIX_ROUTES: Record<string, string> = {
  "首页": "/",
};

/**
 * 全局快捷键监听（AppShell 顶层挂载，渲染 null）。
 *
 * 匹配规则：keydown → 组合串（任意键或组合，须含普通键）→ 与「生效槽位表」逐一比对（已存值优先于默认）。
 * 抑制场景（不触发）：
 *  - 焦点在输入控件（input/textarea/select/contenteditable）——打字不抢键
 *  - 设置模态框打开——正在改快捷键时不触发导航（录键在模态框内自行处理）
 * 浏览器提示：Ctrl+数字 在浏览器标签页模式会被浏览器切标签拦截（独立窗口 / 桌面应用模式无此问题）。
 */
export function GlobalShortcuts() {
  const navigate = useNavigate();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (useSettingsModal.getState().open) return; // 设置开着（含快捷键改键）不触发
      const t = e.target as HTMLElement | null;
      if (t) {
        if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable) return;
      }
      const combo = eventCombo(e);
      if (!combo) return;

      const st = useMenuStore.getState();
      const sst = useShortcutsStore.getState();
      if (!sst.loaded) return;
      const dynMenus = st.menus.map((m) => m.name);
      // 工具列表（菜单序 × 列表序）→ 按序默认组合 Ctrl+Alt+N；自定义/停用存表覆盖默认
      const tools = Object.entries(st.tools)
        .map(([menu, list]) => list.map((t) => ({ menu, name: t.name })))
        .flat();
      const tDefaults = tools.length ? toolDefaults(tools) : undefined;
      const slot = allSlots(sst.map, dynMenus, FIXED_MENUS, tools)
        .find((s) => effectiveCombo(sst.map, s, dynMenus, FIXED_MENUS, tDefaults) === combo);
      if (!slot) return;

      e.preventDefault();
      dispatchSlot(slot, st, navigate);
    };
    window.addEventListener("keydown", onKey, true); // capture：先于页面内其它 keydown 处理
    return () => window.removeEventListener("keydown", onKey, true);
  }, [navigate]);

  return null;
}

/** 槽位 → 动作 */
function dispatchSlot(slot: string, st: ReturnType<typeof useMenuStore.getState>, navigate: (p: string) => void) {
  const toast = useToastStore.getState();

  if (slot === SLOT_PANEL) {
    st.clearActive();
    navigate("/");
    return;
  }

  if (slot.startsWith("dyn:")) {
    const name = slot.slice(4);
    if (!st.menus.some((m) => m.name === name)) return;
    const nav = st.menus.find((m) => m.name === name)?.navigation_bar_name[0] ?? "首页";
    // v2.2.0：顶栏默认只留首页 → 快捷键直达某菜单时同步把它上架到顶栏（否则导航行不显示）
    st.pinMenu(name);
    st.openToolCanvas(name, nav);
    navigate(`/tools/${encodeURIComponent(name)}/${encodeURIComponent(nav)}`);
    return;
  }

  if (slot.startsWith("fix:")) {
    const name = slot.slice(4);
    const route = FIX_ROUTES[name];
    if (!route) return;
    st.clearActive();
    navigate(route);
    return;
  }

  if (slot.startsWith("nav:")) {
    // 「当前菜单栏」：仅当正处某个用户菜单（导航行可见）时生效
    const n = Number(slot.slice(4));
    if (!st.activeMenu) return;
    const nav = st.menus.find((m) => m.name === st.activeMenu)?.navigation_bar_name[n - 1];
    if (!nav) return;
    st.openToolCanvas(st.activeMenu, nav);
    navigate(`/tools/${encodeURIComponent(st.activeMenu)}/${encodeURIComponent(nav)}`);
    return;
  }

  if (slot.startsWith("tool:")) {
    // tool:<菜单>__<工具>：工具名菜单内唯一；菜单名不含「__」约定，取首个 __ 分隔
    const rest = slot.slice(5);
    const sep = rest.indexOf("__");
    if (sep < 0) return;
    const menu = rest.slice(0, sep);
    const name = rest.slice(sep + 2);
    // 统一启动入口：优先用菜单元数据里的启动方式与路径（链接打开走内置浏览器）
    const meta = st.tools[menu]?.find((t) => t.name === name);
    void launchTool(menu, name, navigate, { runType: meta?.runType, url: meta?.path })
      .then((r) => toast.push("ok", r.message))
      .catch((err) => toast.push("err", `启动「${name}」失败：${err instanceof Error ? err.message : String(err)}`));
  }
}
