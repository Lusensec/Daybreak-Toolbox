import { create } from "zustand";
import { sendCommand, subscribeEvent } from "../../services/ws";

/** SSH 主机（config/ssh_hosts.json，与 bridge/ssh_service.py 同构） */
export interface SshHost {
  alias: string;
  host: string;
  port?: number;
  username: string;
  password?: string;
}

/**
 * SSH 终端 store：主机表 + 当前激活的远端会话（终端管理页据此切 本地/远端 模式）。
 *  - select(alias)：选中即连接（bridge 常驻 paramiko 会话）；选 "" 回本地终端并断开
 *  - 订阅 ssh.hosts.changed（终端设置保存后下拉框即时刷新）/ ssh.closed（会话断开清状态）
 */
interface SshStore {
  hosts: SshHost[];
  loaded: boolean;
  /** 当前激活的远端会话别名（null = 本地终端） */
  activeAlias: string | null;
  /** 连接中的别名（下拉框转圈指示） */
  connecting: string | null;
  load: () => Promise<void>;
  select: (alias: string | null) => Promise<void>;
}

export const useSshStore = create<SshStore>((set, get) => ({
  hosts: [],
  loaded: false,
  activeAlias: null,
  connecting: null,

  load: async () => {
    try {
      const r = await sendCommand("ssh.hosts.get", {});
      set({ hosts: (r.hosts ?? []) as SshHost[], loaded: true });
    } catch { /* WS 未上线：稍后 ssh.hosts.changed / 再次打开时再拉 */ }
  },

  select: async (alias) => {
    if (!alias) {
      // 回本地终端：断开当前会话（bridge 侧会话释放；本地终端会话始终独立存在）
      if (get().activeAlias) {
        await sendCommand("ssh.close", { alias: get().activeAlias }).catch(() => {});
      }
      set({ activeAlias: null, connecting: null });
      return;
    }
    if (!get().hosts.some((h) => h.alias === alias)) return;
    set({ connecting: alias });
    try {
      await sendCommand("ssh.connect", { alias });
      set({ activeAlias: alias, connecting: null });
    } catch (e) {
      set({ connecting: null });
      throw new Error(`SSH 连接失败：${e instanceof Error ? e.message : String(e)}`);
    }
  },
}));

let _subscribed = false;
/** 订阅广播 + 首次加载（AppShell 启动时调用一次） */
export function bindSshEvents() {
  if (_subscribed) return;
  _subscribed = true;
  subscribeEvent("ssh.hosts.changed", (payload) => {
    const p = payload as { hosts?: SshHost[] };
    useSshStore.setState({ hosts: p.hosts ?? [], loaded: true });
  });
  subscribeEvent("ssh.closed", (payload) => {
    const p = payload as { alias?: string; reason?: string };
    const s = useSshStore.getState();
    if (p.alias && s.activeAlias === p.alias) {
      // 会话被远端断开 / 命令失败丢失 → 终端页自动回本地模式（状态栏可见原因）
      useSshStore.setState({ activeAlias: null, connecting: null });
    }
  });
  void useSshStore.getState().load();
}
