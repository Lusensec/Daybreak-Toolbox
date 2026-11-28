import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { Package, Loader2, Plus, X } from "lucide-react";
import { sendCommand, subscribeEvent } from "../services/ws";
import { useMenuStore } from "../features/menu/store";
import { launchTool } from "../features/browser/launch";
import { useToast } from "../components/toast";
import { useSettingsModal } from "../store/settingsModal";
import { CtxMenu, type CtxItem, type CtxState } from "../components/DynamicMenuNav";
import { promptOpen } from "../components/PromptDialog";
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

/** 启动方式候选项（与 bridge menu_service.RUN_TYPES 一致；前端只做展示/选择） */
const RUN_TYPE_OPTIONS = ["直接打开", "命令行打开", "文件夹打开", "链接打开", "下载链接"] as const;

/**
 * 工具画布页（/tools/:menu/:nav）—— Web 端 1:1 复刻旧版 canvas 工具按钮区。
 *  - 数据源：bridge tool.grid（按 菜单 + 导航 取 config/config.json 中 菜单→导航→工具 结构）
 *  - 点击工具 → bridge tool.run（在本机执行 5 种启动方式）
 *  - v2.2.5：工具卡右键菜单（加入/移除首页 / 打开所在文件夹 / 改名·路径·运行方式·命令 / 删除 / 属性）
 *            + 卡片按住拖拽栏内排序（tool.reorder 落库）
 *  - 置灰规则：相对/绝对路径不存在 → 禁用（旧版 is_tool_path_active 语义）。
 *    注意：不再用 disabled 属性——disabled 按钮收不到 pointer/context 事件，
 *    置灰卡也要能右键编辑路径（修完路径才能用），点击由 onClick 守卫拦截。
 */
export function ToolCanvas() {
  const { menu = "", nav = "首页" } = useParams();
  const navigate = useNavigate();
  const [tools, setTools] = useState<ToolItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const toast = useToast();
  const openSettings = useSettingsModal((s) => s.openModal);
  const menus = useMenuStore((s) => s.menus);
  const menuInfo = menus.find((m) => m.name === menu);

  // ---- v2.2.5：首页固定（pin）集合，key = `${menu}::${name}` ----
  const [pins, setPins] = useState<Set<string>>(new Set());
  const loadPins = async () => {
    try {
      const r = await sendCommand("home.tools.get", {});
      setPins(new Set(((r.tools ?? []) as { menu: string; name: string }[]).map((p) => `${p.menu}::${p.name}`)));
    } catch { /* 首页固定列表取不到不阻塞画布 */ }
  };

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
    void loadPins();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [menu, nav]);

  // v2.2.0：菜单/工具变更（设置页增删工具、右键删除）后自动重载当前画布，
  // 避免「工具已删除但画布还挂着旧按钮」；v2.2.5：pin 列表同步刷新
  useEffect(() => {
    const un = subscribeEvent("menu.changed", () => { void loadGrid(); void loadPins(); });
    return un;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [menu, nav]);

  async function runTool(name: string) {
    const tool = tools.find((t) => t.工具名称 === name);
    setBusy(name);
    try {
      // 统一启动入口：链接打开走内置浏览器，其余走 bridge tool.run
      const r = await launchTool(menu, name, navigate, { runType: tool?.启动方式, url: tool?.工具路径 });
      toast.ok(r.message);
      // 仅本机启动才需重载网格（下载回写后路径可能已变）；内置浏览器打开无需刷新
      if (!r.internal) await loadGrid();
    } catch (e) {
      toast.err(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy("");
    }
  }

  // ================= v2.2.5：右键菜单 =================
  const [ctx, setCtx] = useState<(CtxState & { tool: ToolItem }) | null>(null);
  const [runPick, setRunPick] = useState<ToolItem | null>(null);
  const [runSel, setRunSel] = useState<string>(RUN_TYPE_OPTIONS[0]);
  const [propsTool, setPropsTool] = useState<ToolItem | null>(null);

  const errToast = (e: unknown, prefix = "操作失败") =>
    toast.err(`${prefix}：${e instanceof Error ? e.message : String(e)}`);

  function toolCtxItems(t: ToolItem): CtxItem[] {
    const noop = () => {};
    const pinned = pins.has(`${menu}::${t.工具名称}`);
    return [
      pinned
        ? {
            label: "移除首页", icon: "star",
            run: async () => {
              try {
                await sendCommand("home.tools.remove", { menu, name: t.工具名称 });
                toast.ok(`已从首页移除「${t.工具名称}」`);
              } catch (e) { errToast(e); }
            },
          }
        : {
            label: "加入首页", icon: "star",
            run: async () => {
              try {
                await sendCommand("home.tools.add", { menu, name: t.工具名称 });
                toast.ok(`「${t.工具名称}」已固定到首页`);
              } catch (e) { errToast(e); }
            },
          },
      { label: "", sep: true, run: noop },
      {
        label: "打开所在文件夹", icon: "folder",
        run: async () => {
          try {
            const r = await sendCommand("tool.open_folder", { menu, name: t.工具名称 });
            toast.ok(`已打开：${String(r.folder ?? "")}`);
          } catch (e) { errToast(e); }
        },
      },
      { label: "", sep: true, run: noop },
      {
        label: "修改工具名称", icon: "pencil",
        run: async () => {
          const nn = await promptOpen(`修改工具名称（原：${t.工具名称}）`, t.工具名称);
          if (nn === null) return;
          try {
            await sendCommand("tool.update", { menu, name: t.工具名称, new_name: nn });
            toast.ok(`已改名为「${nn}」`);
          } catch (e) { errToast(e); }
        },
      },
      {
        label: "修改工具路径", icon: "pencil",
        run: async () => {
          const np = await promptOpen(`修改工具路径（原：${t.工具路径}）`, t.工具路径);
          if (np === null) return;
          try {
            await sendCommand("tool.update", { menu, name: t.工具名称, new_path: np });
            toast.ok("工具路径已更新");
          } catch (e) { errToast(e); }
        },
      },
      {
        label: "修改运行方式", icon: "pencil",
        run: () => { setRunSel(t.启动方式); setRunPick(t); },
      },
      {
        label: "修改启动命令", icon: "pencil",
        run: async () => {
          const nc = await promptOpen(`修改启动命令（原：${t.工具命令 || "空"}）`, t.工具命令);
          if (nc === null) return;
          try {
            await sendCommand("tool.update", { menu, name: t.工具名称, command: nc });
            toast.ok("启动命令已更新");
          } catch (e) { errToast(e); }
        },
      },
      { label: "", sep: true, run: noop },
      {
        label: "删除工具", icon: "trash", danger: true,
        run: async () => {
          try {
            await sendCommand("menu.remove_tool", { menu, name: t.工具名称 });
            toast.ok(`已删除「${t.工具名称}」`);
          } catch (e) { errToast(e); }
        },
      },
      { label: "属性", icon: "info", run: () => setPropsTool(t) },
    ];
  }

  async function submitRunType() {
    if (!runPick) return;
    try {
      await sendCommand("tool.update", { menu, name: runPick.工具名称, run_type: runSel });
      toast.ok(`运行方式已改为「${runSel}」`);
    } catch (e) { errToast(e); }
    setRunPick(null);
  }

  // ================= v2.2.5：卡片拖拽排序 =================
  const toolsRef = useRef<ToolItem[]>([]);
  useEffect(() => { toolsRef.current = tools; }, [tools]);
  const dragState = useRef<{ idx: number; x: number; y: number; armed: boolean } | null>(null);
  const [dragIdx, setDragIdx] = useState(-1);
  const clickSuppressed = useRef(false); // 拖拽松手后吞掉随之而来的 click（否则误启动工具）

  function onDragMove(e: PointerEvent) {
    const ds = dragState.current;
    if (!ds) return;
    if (!ds.armed) {
      if (Math.abs(e.clientX - ds.x) + Math.abs(e.clientY - ds.y) < 5) return;
      ds.armed = true;
      setDragIdx(ds.idx);
      document.body.classList.add("tool-grid--dragging");
    }
    // 拖拽中的卡 pointer-events:none → elementFromPoint 命中的是其下方卡片
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const card = el?.closest?.(".tool-btn") as HTMLElement | null;
    const ti = card && card.dataset.idx !== undefined ? Number(card.dataset.idx) : -1;
    if (ti >= 0 && ti !== ds.idx && ti < toolsRef.current.length) {
      const arr = [...toolsRef.current];
      const [moved] = arr.splice(ds.idx, 1);
      arr.splice(ti, 0, moved);
      toolsRef.current = arr;
      ds.idx = ti;
      setTools(arr);
      setDragIdx(ti);
    }
  }

  function onDragUp() {
    window.removeEventListener("pointermove", onDragMove);
    document.body.classList.remove("tool-grid--dragging");
    const ds = dragState.current;
    dragState.current = null;
    setDragIdx(-1);
    if (ds?.armed) {
      clickSuppressed.current = true;
      setTimeout(() => { clickSuppressed.current = false; }, 150);
      void sendCommand("tool.reorder", { menu, nav, order: toolsRef.current.map((t) => t.工具名称) })
        .then(() => toast.ok("排序已保存"))
        .catch((e) => { errToast(e, "保存排序失败"); void loadGrid(); });
    }
  }

  function onCardPointerDown(e: React.PointerEvent, idx: number) {
    if (e.button !== 0 || busy !== "") return;
    dragState.current = { idx, x: e.clientX, y: e.clientY, armed: false };
    window.addEventListener("pointermove", onDragMove);
    window.addEventListener("pointerup", onDragUp, { once: true });
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
            点击 ＋ 在「{menu} / {nav}」下添加工具
          </div>
        </div>
      ) : (
        <div className={"tool-grid" + (dragIdx >= 0 ? " is-dragging" : "")}>
          {tools.map((t, i) => (
            <button
              key={t.工具名称}
              data-idx={i}
              className={
                "tool-btn" +
                (t.active ? "" : " tool-btn--disabled") +
                ((t.启动方式 === "下载链接" || t.启动方式 === "链接打开") ? " tool-btn--link" : "") +
                (i === dragIdx ? " tool-btn--dragging" : "")
              }
              title={`${t.启动方式} · ${t.工具路径}${t.工具使用 ? "\n用途：" + t.工具使用 : ""}${!t.active ? "\n（路径不存在，已置灰）" : ""}\n按住拖动可排序；右键更多操作`}
              onClick={() => {
                if (clickSuppressed.current) return; // 拖拽松手后的那次 click
                if (!t.active || busy !== "") return;
                void runTool(t.工具名称);
              }}
              onPointerDown={(e) => onCardPointerDown(e, i)}
              onContextMenu={(e) => {
                e.preventDefault();
                setCtx({ x: e.clientX, y: e.clientY, target: { kind: "menu", name: t.工具名称 }, tool: t });
              }}
            >
              {busy === t.工具名称 ? <Loader2 size={14} className="spin" /> : <Package size={14} />}
              <span className="tool-btn__name">{t.工具名称}</span>
              <span className="tool-btn__meta">[{t.启动方式}]</span>
            </button>
          ))}
        </div>
      )}

      {ctx ? (
        <CtxMenu state={ctx} items={toolCtxItems(ctx.tool)} onClose={() => setCtx(null)} />
      ) : null}

      {/* 修改运行方式：单选弹窗（5 种启动方式；校验在后端 tool.update） */}
      {runPick ? (
        <div className="prompt-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) setRunPick(null); }}>
          <div className="prompt-dialog" role="dialog" aria-modal="true">
            <div className="prompt-dialog__title">
              修改运行方式「{runPick.工具名称}」
              <button className="prompt-dialog__close" title="取消" onClick={() => setRunPick(null)}><X size={14} /></button>
            </div>
            <div className="tool-radios">
              {RUN_TYPE_OPTIONS.map((rt) => (
                <label key={rt} className={"tool-radio" + (runSel === rt ? " is-active" : "")}>
                  <input type="radio" name="tool-runtype" checked={runSel === rt} onChange={() => setRunSel(rt)} />
                  {rt}
                </label>
              ))}
            </div>
            <div className="prompt-dialog__row">
              <span className="prompt-dialog__hint">命令行打开需用 * 占位；链接类路径需 http(s)</span>
              <div className="prompt-dialog__btns">
                <button className="prompt-dialog__btn primary" onClick={() => void submitRunType()}>确定</button>
                <button className="prompt-dialog__btn" onClick={() => setRunPick(null)}>取消</button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {/* 属性：只读展示工具全部字段 */}
      {propsTool ? (
        <div className="prompt-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) setPropsTool(null); }}>
          <div className="prompt-dialog" role="dialog" aria-modal="true">
            <div className="prompt-dialog__title">
              工具属性「{propsTool.工具名称}」
              <button className="prompt-dialog__close" title="关闭" onClick={() => setPropsTool(null)}><X size={14} /></button>
            </div>
            <div className="tool-props">
              <div className="tool-props__row"><span className="tool-props__k">名称</span><span className="tool-props__v">{propsTool.工具名称}</span></div>
              <div className="tool-props__row"><span className="tool-props__k">所属菜单</span><span className="tool-props__v">{menu}</span></div>
              <div className="tool-props__row"><span className="tool-props__k">所属导航</span><span className="tool-props__v">{nav}</span></div>
              <div className="tool-props__row"><span className="tool-props__k">运行方式</span><span className="tool-props__v">{propsTool.启动方式}</span></div>
              <div className="tool-props__row"><span className="tool-props__k">工具路径</span><span className="tool-props__v tool-props__v--wrap">{propsTool.工具路径 || "（空）"}</span></div>
              <div className="tool-props__row"><span className="tool-props__k">启动命令</span><span className="tool-props__v tool-props__v--wrap">{propsTool.工具命令 || "（空）"}</span></div>
              <div className="tool-props__row">
                <span className="tool-props__k">路径状态</span>
                <span className={"tool-props__v " + (propsTool.active ? "tool-props__ok" : "tool-props__bad")}>
                  {propsTool.active ? "有效（路径存在 / 链接）" : "无效（路径不存在，已置灰）"}
                </span>
              </div>
            </div>
            <div className="prompt-dialog__row">
              <span className="prompt-dialog__hint">来源：config/config.json</span>
              <div className="prompt-dialog__btns">
                <button className="prompt-dialog__btn primary" onClick={() => setPropsTool(null)}>关闭</button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
