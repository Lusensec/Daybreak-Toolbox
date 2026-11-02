import { create } from "zustand";
import type { TabKey } from "../components/SettingsModal";

/**
 * 设置模态框开合 + 目标定位状态：
 *  - openTab：打开时定位到的标签页（默认 工具管理）
 *  - focusMenu / focusNav：工具管理内预选的 菜单栏/导航栏（如 工具画布空态「＋」直达）
 * 打开后立即消费（useEffect 回写 null / "tools"），不影响下次打开。
 */
interface SettingsModalState {
  open: boolean;
  openTab: TabKey;
  focusMenu: string | null;
  focusNav: string | null;
  openModal: (opts?: { tab?: TabKey; menu?: string; nav?: string }) => void;
  closeModal: () => void;
  consumeFocus: () => void;
}

export const useSettingsModal = create<SettingsModalState>((set, get) => ({
  open: false,
  openTab: "tools",
  focusMenu: null,
  focusNav: null,
  openModal: (opts) => set({
    open: true,
    openTab: opts?.tab ?? "tools",
    focusMenu: opts?.menu ?? null,
    focusNav: opts?.nav ?? null,
  }),
  closeModal: () => set({ open: false }),
  consumeFocus: () => {
    if (get().focusMenu || get().focusNav) set({ focusMenu: null, focusNav: null });
  },
}));
