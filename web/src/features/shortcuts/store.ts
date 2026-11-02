import { create } from "zustand";
import { sendCommand, subscribeEvent } from "../../services/ws";

/**
 * 快捷键设置 store：槽位→组合 扁平表（config/shortcuts.json，整表覆盖保存）。
 *  - setSlot 乐观更新：先本地生效（全局监听立即按新表匹配），失败回滚重拉
 *  - 订阅 shortcut.changed：多窗口 / 后端重开后自动同步
 */
interface ShortcutsStore {
  map: Record<string, string>;
  loaded: boolean;
  load: () => Promise<void>;
  setSlot: (slotKey: string, combo: string) => Promise<void>;
}

export const useShortcutsStore = create<ShortcutsStore>((set, get) => ({
  map: {},
  loaded: false,

  load: async () => {
    try {
      const r = await sendCommand("shortcut.get", {});
      set({ map: (r.shortcuts ?? {}) as Record<string, string>, loaded: true });
    } catch { /* WS 未上线：稍后 shortcut.changed / 重开设置时再拉 */ }
  },

  setSlot: async (slotKey, combo) => {
    const next = { ...get().map, [slotKey]: combo };
    set({ map: next }); // 乐观：全局快捷键立即按新表匹配
    try {
      const r = await sendCommand("shortcut.set", { shortcuts: next });
      set({ map: (r.shortcuts ?? next) as Record<string, string> });
    } catch (e) {
      await get().load(); // 回滚为服务端真实值
      throw new Error(`快捷键保存失败：${e instanceof Error ? e.message : String(e)}`);
    }
  },
}));

let _subscribed = false;
/** 订阅服务端广播 + 首次加载（AppShell 启动时调用一次） */
export function bindShortcutEvents() {
  if (_subscribed) return;
  _subscribed = true;
  subscribeEvent("shortcut.changed", (payload) => {
    const p = payload as { shortcuts?: Record<string, string> };
    useShortcutsStore.setState({ map: p.shortcuts ?? {}, loaded: true });
  });
  void useShortcutsStore.getState().load();
}
