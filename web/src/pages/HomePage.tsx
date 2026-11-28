import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import {
  Settings,
  Wifi,
  WifiOff,
  FolderOpen,
  RefreshCw,
  Star,
  Package,
  X,
} from "lucide-react";
import { useConnStore, sendCommand, subscribeEvent } from "../services/ws";
import { useSettingsModal } from "../store/settingsModal";
import { useMenuStore } from "../features/menu/store";
import { launchTool } from "../features/browser/launch";
import { useToast } from "../components/toast";
import "./HomePage.css";

interface Feature {
  key: string;
  to?: string;
  title: string;
  desc: string;
  icon: React.ComponentType<{ size?: number | string }>;
  action?: "settings";
}

/** v2.2.5：首页固定工具卡（bridge home.tools.get；menu.changed 自动刷新） */
interface HomeTool {
  menu: string;
  name: string;
  nav: string;
  启动方式: string;
  工具路径: string;
  active: boolean;
}

/** v2.1.3：系统固定功能面板（AI 对话 / 汉英翻译 / 编解码 / 终端管理 / 临时笔记）已移除，
 *  首页入口只保留「工具箱设置」；日常使用走下方用户自定义菜单卡。 */
const FEATURES: Feature[] = [
  { key: "settings", title: "工具箱设置", desc: "菜单栏 / 导航栏 / 工具 / 菜单展示 / 快捷键 / 更新记录", icon: Settings, action: "settings" },
];

export function HomePage() {
  const conn = useConnStore((s) => s.status);
  const openSettingsModal = useSettingsModal((s) => s.openModal);
  const navigate = useNavigate();
  const menus = useMenuStore((s) => s.menus);
  const menuLoading = useMenuStore((s) => s.loading);
  const refreshMenus = useMenuStore((s) => s.refresh);
  const toast = useToast();
  const online = conn === "online";

  // ---- v2.2.5：首页固定工具（工具卡右键「加入首页」后出现在这里）----
  const [pinned, setPinned] = useState<HomeTool[]>([]);
  const loadPins = async () => {
    try {
      const r = await sendCommand("home.tools.get", {});
      setPinned((r.tools ?? []) as HomeTool[]);
    } catch { /* 取不到不打扰首页 */ }
  };
  useEffect(() => {
    if (!online) return;
    void loadPins();
    const un = subscribeEvent("menu.changed", () => { void loadPins(); });
    return un;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [online]);

  async function runPinned(p: HomeTool) {
    if (!p.active) { toast.err(`路径不存在：${p.工具路径}`); return; }
    try {
      // 统一启动入口：链接打开走内置浏览器，其余走 bridge tool.run
      const r = await launchTool(p.menu, p.name, navigate, { runType: p.启动方式, url: p.工具路径 });
      toast.ok(r.message);
    } catch (e) {
      toast.err(String(e instanceof Error ? e.message : e));
    }
  }

  async function unpin(p: HomeTool) {
    try {
      await sendCommand("home.tools.remove", { menu: p.menu, name: p.name });
      toast.ok(`已从首页移除「${p.name}」`);
    } catch (e) {
      toast.err(String(e instanceof Error ? e.message : e));
    }
  }

  // 点菜单卡 → 该菜单上架到顶栏（v2.2.0）+ 进该菜单第一个导航的工具画布页
  function openMenu(name: string, navs: string[]) {
    const st = useMenuStore.getState();
    st.pinMenu(name);
    const nav = navs[0] ?? "首页";
    st.openToolCanvas(name, nav);
    navigate(`/tools/${encodeURIComponent(name)}/${encodeURIComponent(nav)}`);
  }

  return (
    <div className="home">
      <div className="card home-card">
        <h1 className="home-title">破晓·工具箱</h1>
        <p className="home-sub">Daybreak Toolbox · Web 端</p>

        <div className="home-status" data-state={online ? "online" : "offline"}>
          {online ? <Wifi size={14} /> : <WifiOff size={14} />}
          <span>桥接 {conn === "online" ? "已连接" : conn === "reconnecting" ? "重连中…" : conn === "connecting" ? "连接中…" : "未连接"}</span>
        </div>
      </div>

      {/* v2.2.5：置顶工具（工具卡右键「加入首页」固定到这里，点击直接启动） */}
      {online && pinned.length > 0 ? (
        <div className="home-menus">
          <div className="home-menus__head">
            <span className="home-menus__title"><Star size={14} /> 置顶工具</span>
            <span className="home-menus__hint">在工具画布里右键工具卡「加入首页」固定到这里</span>
          </div>
          <div className="home-grid">
            {pinned.map((p) => (
              <button
                key={`${p.menu}::${p.name}`}
                className={"home-tile home-tile--tool" + (p.active ? "" : " home-tile--tool-off")}
                onClick={() => void runPinned(p)}
                title={`${p.menu} / ${p.nav} · ${p.启动方式}${p.active ? "" : "\n（路径不存在，已置灰）"}`}
              >
                <span className="home-tile__icon"><Package size={16} /></span>
                <span className="home-tile__title">{p.name}</span>
                <span className="home-tile__desc">{p.menu} / {p.nav}</span>
                <span
                  className="home-tile__unpin"
                  title="从首页移除"
                  onClick={(e) => { e.stopPropagation(); void unpin(p); }}
                >
                  <X size={12} />
                </span>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {/* 动态用户菜单（config.json，menu.list 数据驱动，置顶展示） */}
      <div className="home-menus">
        <div className="home-menus__head">
          <span className="home-menus__title"><FolderOpen size={14} /> 我的菜单</span>
          <span className="home-menus__hint">来自 config/config.json，点卡片进入工具画布</span>
          <button
            className="home-menus__refresh"
            title="刷新菜单"
            onClick={() => void refreshMenus()}
            disabled={menuLoading || !online}
          >
            <RefreshCw size={12} className={menuLoading ? "spin" : ""} /> 刷新
          </button>
        </div>
        {menus.length === 0 ? (
          <div className="home-menus__empty">
            {online
              ? "暂无自定义菜单 —— 在「工具箱设置 → 菜单管理」添加菜单栏后会显示在这里"
              : "桥接未连接，菜单列表暂不可用"}
          </div>
        ) : (
          <div className="home-grid">
            {menus.map((m) => (
              <button
                key={m.name}
                className="home-tile home-tile--menu"
                onClick={() => openMenu(m.name, m.navigation_bar_name)}
                title={m.navigation_bar_name.join(" / ")}
              >
                <span className="home-tile__icon">
                  <span className="home-menu-dot" style={{ background: m.menu_color || "#2980b9" }} />
                </span>
                <span className="home-tile__title">{m.name}</span>
                <span className="home-tile__desc">
                  {m.navigation_bar_name.length} 个导航 · {m.tool_count} 个工具
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* 系统卡（v2.1.3：只剩「工具箱设置」；其余固定功能面板已移除） */}
      <div className="home-grid">
        {FEATURES.map((f) => {
          const Icon = f.icon;
          if (f.action === "settings") {
            return (
              <button key={f.key} className="home-tile home-tile--btn" onClick={() => openSettingsModal()}>
                <span className="home-tile__icon"><Icon size={18} /></span>
                <span className="home-tile__title">{f.title}</span>
                <span className="home-tile__desc">{f.desc}</span>
              </button>
            );
          }
          return (
            <Link key={f.key} to={f.to!} className="home-tile">
              <span className="home-tile__icon">
                <Icon size={18} />
              </span>
              <span className="home-tile__title">{f.title}</span>
              <span className="home-tile__desc">{f.desc}</span>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
