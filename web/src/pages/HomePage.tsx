import { Link, useNavigate } from "react-router";
import {
  Settings,
  Wifi,
  WifiOff,
  FolderOpen,
  RefreshCw,
} from "lucide-react";
import { useConnStore } from "../services/ws";
import { useSettingsModal } from "../store/settingsModal";
import { useMenuStore } from "../features/menu/store";
import "./HomePage.css";

interface Feature {
  key: string;
  to?: string;
  title: string;
  desc: string;
  icon: React.ComponentType<{ size?: number | string }>;
  action?: "settings";
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
  const online = conn === "online";

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
