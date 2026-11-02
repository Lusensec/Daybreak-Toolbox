import { useEffect, useState } from "react";
import { useParams, Link } from "react-router";
import { Package, Loader2, Plus } from "lucide-react";
import { sendCommand } from "../services/ws";
import { useMenuStore } from "../features/menu/store";
import { useToast } from "../components/toast";
import { useSettingsModal } from "../store/settingsModal";
import "./ToolCanvas.css";

interface ToolItem {
  工具名称: string;
  工具路径: string;
  工具使用: string;
  启动方式: string;
  工具命令: string;
  active: boolean;
  index: number;
}

/**
 * 工具画布页（/tools/:menu/:nav）—— Web 端 1:1 复刻旧版 canvas 工具按钮区。
 *  - 数据源：bridge tool.grid（按 菜单 + 导航 取 config/config.json 中 菜单→导航→工具 结构）
 *  - 点击工具 → bridge tool.run（在本机执行 5 种启动方式）
 *  - 置灰规则：相对/绝对路径不存在 → 禁用（旧版 is_tool_path_active 语义）
 *  - 下载链接/链接类文字蓝色（旧版 fg="blue"）
 */
export function ToolCanvas() {
  const { menu = "", nav = "首页" } = useParams();
  const [tools, setTools] = useState<ToolItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const toast = useToast();
  const openSettings = useSettingsModal((s) => s.openModal);
  const menus = useMenuStore((s) => s.menus);
  const menuInfo = menus.find((m) => m.name === menu);

  const loadGrid = async () => {
    setLoading(true);
    setErr("");
    try {
      const r = await sendCommand("tool.grid", { menu, nav });
      setTools((r.tools ?? []) as ToolItem[]);
    } catch (e) {
      setErr(String(e instanceof Error ? e.message : e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadGrid();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [menu, nav]);

  async function runTool(name: string) {
    setBusy(name);
    try {
      const r = await sendCommand("tool.run", { menu, name });
      toast.ok(String(r.message ?? "已启动"));
      await loadGrid(); // 下载回写后刷新（路径可能已变）
    } catch (e) {
      toast.err(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="tool-canvas">
      <div className="tool-canvas__head">
        <span className="tool-canvas__crumb">
          {menuInfo ? (
            <span className="tool-canvas__dot" style={{ background: menuInfo.menu_color || "#2980b9" }} />
          ) : null}
          <strong>{menu || "（菜单不存在）"}</strong>
          <span className="tool-canvas__sep">/</span>
          <span>{nav}</span>
        </span>
        <Link to="/" className="tool-canvas__home">← 返回</Link>
      </div>

      {loading ? (
        <div className="tool-canvas__empty"><Loader2 size={16} className="spin" /> 加载工具中…</div>
      ) : err ? (
        <div className="tool-canvas__empty tool-canvas__empty--err">
          {String(err).includes("MENU_NOT_FOUND") ? "该菜单不存在（可能已被删除）" : `加载失败：${err}`}
        </div>
      ) : tools.length === 0 ? (
        <div className="tool-canvas__empty">
          <div>「{menu} / {nav}」下暂无工具</div>
          <button
            className="tool-canvas__add"
            title={`在「${menu} / ${nav}」下添加工具`}
            onClick={() => openSettings({ tab: "tools", menu, nav })}
          >
            <Plus size={26} />
          </button>
          <div className="tool-canvas__hint">
            点击 ＋ 在「{menu} / {nav}」下添加工具（工具存于 config/config.json，相对路径基于「{menu} / {nav}」目录）
          </div>
        </div>
      ) : (
        <div className="tool-grid">
          {tools.map((t) => (
            <button
              key={t.工具名称}
              className={
                "tool-btn" +
                (t.active ? "" : " tool-btn--disabled") +
                ((t.启动方式 === "下载链接" || t.启动方式 === "链接打开") ? " tool-btn--link" : "")
              }
              title={`${t.启动方式} · ${t.工具路径}${t.工具使用 ? "\n用途：" + t.工具使用 : ""}${!t.active ? "\n（路径不存在，已置灰）" : ""}`}
              disabled={!t.active || busy !== ""}
              onClick={() => void runTool(t.工具名称)}
            >
              {busy === t.工具名称 ? <Loader2 size={14} className="spin" /> : <Package size={14} />}
              <span className="tool-btn__name">{t.工具名称}</span>
              <span className="tool-btn__meta">[{t.启动方式}]</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
