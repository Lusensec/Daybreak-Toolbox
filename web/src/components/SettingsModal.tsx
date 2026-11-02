import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { X, Plus, Trash2, RefreshCw, FolderOpen, Eye, EyeOff, Wrench, Brain, Save, ChevronDown, Languages, Keyboard, Server, Download, Star, CircleDot } from "lucide-react";
import { sendCommand, subscribeEvent } from "../services/ws";
import { AboutDialog } from "./AboutDialog";
import { useToast } from "./toast";
import { useSettingsModal } from "../store/settingsModal";
import { FIXED_MENUS } from "../features/menu/fixedMenus";
import { useDraggable } from "../hooks/useDraggable";
import { useResize } from "../hooks/useResize";
import { KeyCapture } from "../features/shortcuts/KeyCapture";
import { useShortcutsStore } from "../features/shortcuts/store";
import { findConflicts, SHORTCUT_FIX_MENUS, SLOT_PANEL, defaultToolCombo, slotDyn, slotFix, slotNav, slotTool } from "../features/shortcuts/shortcuts";
import "./SettingsModal.css";

export type TabKey = "tools" | "ai" | "translate" | "shortcuts" | "terminal" | "display" | "ball" | "update";

interface MenuInfo {
  name: string;
  menu_path: string;
  menu_color: string;
  navigation_bar_name: string[];
  tool_count: number;
  /** 显隐参数：1 显示 / 0 隐藏（缺省 1） */
  menu_visible?: number;
}

interface ToolInfo {
  工具名称: string;
  工具路径: string;
  启动方式: string;
  工具命令: string;
  /** 所属导航栏名（新模型：结构即数据，list_tools 展平回带） */
  nav?: string;
}

interface AiModelCfg {
  AI_API: string;
  AI_alias?: string;
  AI_base_url?: string;
  AI_model_id?: string;
  AI_kind?: string;
  ai_color: string;
  use_page: number;
}
interface AiConfig {
  models: string[];        // 后端已按别名排序
  kinds: string[];        // ["openai","zhipu","ollama"]
  config: Record<string, AiModelCfg>;
}

// 工具管理提供的启动方式（按需求去掉「下载链接」；后端仍兼容历史数据）
const RUN_TYPES = ["直接打开", "命令行打开", "文件夹打开", "链接打开"];

/** 模型下拉显示：优先别名，括号内附内部名 */
function modelDisplay(cfg: AiConfig, name: string): string {
  const alias = (cfg.config[name]?.AI_alias ?? "").trim();
  return alias ? `${alias}（${name}）` : name;
}

/** 密钥掩码：保留首 3 + 尾 4，中间以 * 代替（过短则整段 *）；空串返回空串。 */
function maskSecret(s: string): string {
  if (!s) return "";
  if (s.length <= 7) return "*".repeat(s.length);
  return s.slice(0, 3) + "*".repeat(s.length - 7) + s.slice(-4);
}

/**
 * 工具箱设置模态框（固定 960x580，右侧按钮 / 首页卡 点击打开）。
 * 标签页（导航栏管理独立，位于菜单管理与工具管理中间）：
 *  菜单管理 → 导航栏管理 → 工具管理 → AI模型设置 → 更新记录
 *  - 菜单管理：菜单栏增删（menu.add/remove）
 *  - 导航栏管理：挂在某菜单栏下的导航入口（menu.add_nav/remove_nav）
 *  - 工具管理：menu.add_tool/remove_tool + menu.list_tools
 *  - AI模型设置：ai.get_config/set_config/add_model/remove_model/test，
 *    别名必填，使用模型按别名排序动态展示，可增删自定义模型
 * 数据刷新：订阅 menu.changed / ai.config_changed 自动重载。
 */
export function SettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<TabKey>("tools");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  // 打开定位参数（store 提供，打开后消费一次）：指定标签页 + 工具管理内预选 菜单栏/导航栏
  const openTab = useSettingsModal((s) => s.openTab);
  const focusMenu = useSettingsModal((s) => s.focusMenu);
  const focusNav = useSettingsModal((s) => s.focusNav);
  const consumeFocus = useSettingsModal((s) => s.consumeFocus);

  // 模态框可拖拽（项目约定：所有模态框统一走 useDraggable，把手 = 标题栏）
  const panelRef = useRef<HTMLDivElement>(null);
  const headRef = useRef<HTMLDivElement>(null);
  const { dragging, handleProps } = useDraggable(panelRef, headRef);

  // 模态框可拉伸（右下角把手；min/max 约束，max 自动钳制到视口；重开复位为默认 960x580）
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const { onPointerDown: onResizeStart, resizing } = useResize({
    min: { w: 680, h: 420 },
    max: { w: 1600, h: 1000 },
    getStartSize: () => size ?? { w: 960, h: 580 },
    onResize: (w, h) => setSize({ w, h }),
  });

  // ---- 工具管理状态（菜单栏/导航栏/工具 三合一）----
  const [menus, setMenus] = useState<MenuInfo[]>([]);
  const [menuName, setMenuName] = useState("");
  const [menuColor, setMenuColor] = useState("#2980b9");
  const [navName, setNavName] = useState("");
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [activeMenu, setActiveMenu] = useState("");
  const [activeNav, setActiveNav] = useState("");          // 当前工具归属的导航栏（工具使用 字段）
  const [addMenuOpen, setAddMenuOpen] = useState(false);   // 第 1 行 ＋ 展开「新增菜单栏」输入行
  const [addNavOpen, setAddNavOpen] = useState(false);     // 第 2 行 ＋ 展开「新增导航栏」输入行
  const [fixedVis, setFixedVis] = useState<Record<string, number>>({}); // 固定菜单栏显隐表（config.json __fixed_menu_visible__）
  // 最新所选菜单栏（ref 镜像）：menu.changed 订阅回调闭包会过期，刷新时读 ref 保住用户选择
  const activeMenuRef = useRef(activeMenu);
  useEffect(() => { activeMenuRef.current = activeMenu; }, [activeMenu]);
  const [tName, setTName] = useState("");
  const [tPath, setTPath] = useState("");
  const [tRun, setTRun] = useState(RUN_TYPES[0]);
  const [tCmd, setTCmd] = useState("");
  const isLink = tRun === "链接打开" || tRun === "下载链接"; // 链接类：路径为 http(s)，不弹文件管理器

  /** 第 2 行右侧按钮：bridge 在本机弹原生文件管理器（选文件/选文件夹），结果回填路径输入框 */
  async function pickPath() {
    const isFolder = tRun === "文件夹打开";
    try {
      const r = await sendCommand(isFolder ? "dialog.pick_folder" : "dialog.pick_file", {
        title: isFolder ? "选择工具文件夹" : "选择工具路径",
      });
      const path = String(r.path ?? "");
      if (path) {
        setTPath(path);
        toast.ok("路径已回填");
      } else {
        toast.info("已取消选择（输入框保持不变）");
      }
    } catch (e) {
      toast.err(`文件选择失败：${e instanceof Error ? e.message : e}`);
    }
  }

  // ---- AI 配置状态 ----
  const [ai, setAi] = useState<AiConfig>({ models: [], kinds: [], config: {} });
  const [aiModel, setAiModel] = useState("");
  const [aiAlias, setAiAlias] = useState("");
  const [aiKind, setAiKind] = useState("openai");
  const [aiBaseUrl, setAiBaseUrl] = useState("");
  const [aiApi, setAiApi] = useState("");
  const [aiModelId, setAiModelId] = useState("");
  const [aiPage, setAiPage] = useState(1);
  const [aiModelTwo, setAiModelTwo] = useState("");
  const [aiHistory, setAiHistory] = useState(20); // 历史轮数（10..100）
  const [aiTesting, setAiTesting] = useState(false);
  // 模型行展开态（点击行尾三角展开该模型的配置表单；默认不展开）
  const [expandedModel, setExpandedModel] = useState("");
  // 新增模型表单
  const [newModel, setNewModel] = useState("");
  const [newAlias, setNewAlias] = useState("");

  // ---- 翻译设置状态（百度翻译凭证；存 config/bridge_secrets.json，保存即生效）----
  const [trAppId, setTrAppId] = useState("");
  const [trSecret, setTrSecret] = useState("");            // 用户输入的新密钥（未改则留空）
  const [trLoadedSecret, setTrLoadedSecret] = useState(""); // 服务端当前密钥（掩码/明文回显源）
  const [trSecretTouched, setTrSecretTouched] = useState(false); // 用户是否已输入新密钥
  const [trSecretShown, setTrSecretShown] = useState(false);    // 小眼睛：明文 / 掩码
  const [trConfigured, setTrConfigured] = useState(false);
  const [trTesting, setTrTesting] = useState(false);

  // 掩码/明文回显：有效密钥 = 用户输入过取输入值，否则取服务端现值；
  // 默认掩码（* 代替中间），聚焦 / 点小眼睛 → 明文，再点小眼睛 → 掩码
  const trRaw = trSecretTouched ? trSecret : trLoadedSecret;
  const trSecretDisplay = trSecretShown ? trRaw : maskSecret(trRaw);

  const refreshTranslateCreds = useCallback(async () => {
    try {
      const r = await sendCommand("translate.get_creds", {});
      setTrAppId(String((r as { app_id?: string }).app_id ?? ""));
      setTrConfigured(Boolean((r as { configured?: boolean }).configured));
      setTrLoadedSecret(String((r as { secret_key?: string }).secret_key ?? ""));
      // 重新拉取服务端密钥：清空用户输入态，回到「服务端密钥掩码回显」
      setTrSecret("");
      setTrSecretTouched(false);
      setTrSecretShown(false);
    } catch { /* 断连忽略，保持当前值 */ }
  }, []);

  // 测试翻译：先落盘当前表单（密钥= 有效值：用户输入优先，否则服务端现值），再真实调一次百度接口验证
  async function runTranslateTest() {
    setTrTesting(true);
    try {
      await sendCommand("translate.set_creds", { app_id: trAppId, secret_key: trRaw });
      const req_id = crypto.randomUUID();
      let settled = false;
      const done = (fn: () => void) => { if (!settled) { settled = true; unRes(); unErr(); fn(); setTrTesting(false); } };
      const unRes = subscribeEvent("translate.result", (p: unknown) => {
        const ev = p as { req_id?: string; text?: string; ok?: boolean };
        if (ev.req_id !== req_id) return;
        if (ev.ok) done(() => toast.ok(`翻译正常：「你好」→ ${ev.text}`));
        else done(() => toast.err(String(ev.text ?? "翻译失败")));
      });
      const unErr = subscribeEvent("translate.error", (p: unknown) => {
        const ev = p as { req_id?: string; message?: string };
        if (ev.req_id !== req_id) return;
        done(() => toast.err(String(ev.message ?? "翻译调用失败")));
      });
      await sendCommand("translate.run", { req_id, text: "你好" });
      // 兜底：15s 未收到事件（断网/凭证错误时 service 仍会广播，此为防 UI 卡死）
      setTimeout(() => done(() => toast.err("测试超时（15s 未返回）")), 15000);
    } catch (e) {
      toast.err(String(e instanceof Error ? e.message : e));
      setTrTesting(false);
    }
  }

  // ---- 快捷键设置状态（config/shortcuts.json 槽位→组合表；整表覆盖保存即时生效）----
  const scMap = useShortcutsStore((s) => s.map);
  const [scTools, setScTools] = useState<{ menu: string; nav: string; name: string }[]>([]);
  const [scToolQ, setScToolQ] = useState("");
  const dynNames = useMemo(() => menus.map((m) => m.name), [menus]);
  // 工具列表（扁平化：菜单序 × 列表序）——工具默认编号与冲突检测共用
  const scToolList = useMemo(() => scTools.map((t) => ({ menu: t.menu, name: t.name })), [scTools]);
  // 冲突集合：两个以上槽位生效同一组合（含默认组合之间的撞车；工具默认 Ctrl+Alt+N 亦参与）
  const scConflicts = useMemo(() => findConflicts(scMap, dynNames, FIXED_MENUS, scToolList), [scMap, dynNames, scToolList]);
  const scFiltered = scTools.filter((t) => !scToolQ || `${t.menu}/${t.nav}/${t.name}`.toLowerCase().includes(scToolQ.toLowerCase()));

  // 打开快捷键标签：按需拉全量工具（逐菜单 menu.list_tools）+ 确保快捷键表已加载
  useEffect(() => {
    if (tab !== "shortcuts") return;
    void useShortcutsStore.getState().load();
    let cancel = false;
    (async () => {
      const all = await Promise.all(menus.map(async (m) => {
        try {
          const r = await sendCommand("menu.list_tools", { menu: m.name });
          return ((r.tools ?? []) as ToolInfo[]).map((t) => ({ menu: m.name, nav: String(t.nav ?? ""), name: t.工具名称 }));
        } catch { return [] as { menu: string; nav: string; name: string }[]; }
      }));
      if (!cancel) setScTools(all.flat());
    })();
    return () => { cancel = true; };
  }, [tab, menus]);

  // ---- 终端设置状态（SSH 主机表 config/ssh_hosts.json；列表增删改，整表覆盖保存）----
  interface SshRow { alias: string; host: string; port: string; username: string; password: string; showPw: boolean; }
  const emptySshRow = (): SshRow => ({ alias: "", host: "", port: "", username: "", password: "", showPw: false });
  const [sshRows, setSshRows] = useState<SshRow[]>([emptySshRow()]);
  const [sshLoaded, setSshLoaded] = useState(false);
  const [sshSaving, setSshSaving] = useState(false);

  // 打开终端设置标签：拉主机表回填（空表给一行空白待填）
  useEffect(() => {
    if (tab !== "terminal") return;
    let cancel = false;
    sendCommand("ssh.hosts.get", {})
      .then((r) => {
        if (cancel) return;
        const hosts = (r.hosts ?? []) as { alias: string; host: string; port?: number; username: string; password?: string }[];
        setSshRows(hosts.length
          ? hosts.map((h) => ({ alias: h.alias, host: h.host, port: String(h.port ?? 22), username: h.username, password: h.password ?? "", showPw: false }))
          : [emptySshRow()]);
        setSshLoaded(true);
      })
      .catch(() => { if (!cancel) setSshLoaded(true); });
    return () => { cancel = true; };
  }, [tab]);

  function updateSshRow(i: number, patch: Partial<SshRow>) {
    setSshRows((rows) => rows.map((r, ri) => (ri === i ? { ...r, ...patch } : r)));
  }

  async function saveSshHosts() {
    // 客户端先校验（与后端 ssh_service.normalize_hosts 同规则；服务端仍会兜底校验）
    const seen = new Set<string>();
    for (const row of sshRows) {
      const alias = row.alias.trim();
      const host = row.host.trim();
      const username = row.username.trim();
      const port = row.port.trim();
      if (!alias || !host || !username) { toast.err("别称、地址、用户名均必填（密码可留空走密钥登录）"); return; }
      if (/\s/.test(alias)) { toast.err(`别称「${alias}」不能含空格`); return; }
      if (seen.has(alias)) { toast.err(`别称「${alias}」重复`); return; }
      seen.add(alias);
      if (port !== "") {
        const pn = Number(port);
        if (!Number.isInteger(pn) || pn < 1 || pn > 65535) { toast.err(`「${alias}」端口须为 1-65535 的整数（或留空用 22）`); return; }
      }
    }
    setSshSaving(true);
    try {
      await sendCommand("ssh.hosts.save", {
        hosts: sshRows.map((r) => {
          const o: Record<string, unknown> = {
            alias: r.alias.trim(), host: r.host.trim(),
            username: r.username.trim(), password: r.password,
          };
          if (r.port.trim()) o.port = Number(r.port.trim());
          return o;
        }),
      });
      toast.ok("SSH 主机设置已保存（config/ssh_hosts.json，下拉框即时同步）");
    } catch (e) {
      toast.err(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSshSaving(false);
    }
  }

  // ---- 更新设置状态（GitHub 仓库配置 config/update.json + 检查更新结果）----
  const [upRepo, setUpRepo] = useState("");
  const [upChecking, setUpChecking] = useState(false);
  type UpResult = { kind: "idle" } | { kind: "ok"; msg: string } | { kind: "update"; msg: string; url: string } | { kind: "err"; msg: string };
  const [upResult, setUpResult] = useState<UpResult>({ kind: "idle" });

  // ---- 悬浮球状态（原生小球：置顶 / 隐藏；config/ball_pos.json 持久化，ball.state 事件同步）----
  const [ballAvail, setBallAvail] = useState(false);
  const [ballTop, setBallTop] = useState(true);
  const [ballHidden, setBallHidden] = useState(false);

  const refreshBall = useCallback(async () => {
    try {
      const r = await sendCommand("ball.get_state", {});
      setBallAvail(Boolean(r.available));
      setBallTop(Boolean(r.topmost));
      setBallHidden(Boolean(r.hidden));
    } catch {
      /* bridge 未连接时保持默认 */
    }
  }, []);

  useEffect(() => {
    void refreshBall();
    const un = subscribeEvent("ball.state", (p: unknown) => {
      const s = p as Record<string, unknown>;
      if (s && typeof s === "object") {
        setBallAvail(Boolean(s.available));
        setBallTop(Boolean(s.topmost));
        setBallHidden(Boolean(s.hidden));
      }
    });
    return un;
  }, [refreshBall]);

  // 打开更新设置标签：拉已存仓库地址
  useEffect(() => {
    if (tab !== "update") return;
    let cancel = false;
    sendCommand("update.repo.get", {})
      .then((r) => { if (!cancel) setUpRepo(String(r.repo ?? "")); })
      .catch(() => {});
    return () => { cancel = true; };
  }, [tab]);

  async function saveUpRepo() {
    try {
      await sendCommand("update.repo.save", { repo: upRepo.trim() });
      toast.ok(upRepo.trim() ? "GitHub 仓库已保存" : "GitHub 仓库已清空");
    } catch (e) {
      toast.err(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }

  async function checkUpdate() {
    setUpChecking(true);
    try {
      const r = await sendCommand("update.check", {});
      if (r.has_update) {
        setUpResult({ kind: "update", msg: `发现新版本 ${String(r.latest_version)}（当前 ${String(r.local_version)}）`, url: String(r.release_url ?? "") });
      } else {
        setUpResult({ kind: "ok", msg: `已是最新版本 ${String(r.local_version)}${r.latest_version ? `（GitHub 最新 ${String(r.latest_version)}）` : ""}` });
      }
    } catch (e) {
      setUpResult({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    } finally {
      setUpChecking(false);
    }
  }

  const refreshMenus = useCallback(async () => {
    try {
      const r = await sendCommand("menu.list", {});
      const list = (r.menus ?? []) as MenuInfo[];
      setMenus(list);
      setFixedVis((r.fixed_visible ?? {}) as Record<string, number>);
      // 读 ref（最新选择）：仍有效则保留，否则落到第一个 —— 增删工具不再重置用户选择
      const cur = activeMenuRef.current && list.some((m) => m.name === activeMenuRef.current)
        ? activeMenuRef.current : list[0]?.name ?? "";
      setActiveMenu(cur);
      if (cur) {
        const r2 = await sendCommand("menu.list_tools", { menu: cur });
        setTools((r2.tools ?? []) as ToolInfo[]);
        // 导航栏选择：当前值仍合法则保留，否则落到第一个
        const navs = list.find((m) => m.name === cur)?.navigation_bar_name ?? [];
        setActiveNav((prev) => (navs.includes(prev) ? prev : navs[0] ?? ""));
      } else {
        setTools([]);
        setActiveNav("");
      }
    } catch (e) {
      toast.err(`菜单列表加载失败：${e}`);
    }
  }, []);

  const refreshAi = useCallback(async () => {
    try {
      const r = await sendCommand("ai.get_config", {});
      const cfg = r as unknown as AiConfig;
      setAi(cfg);
      // 布局还原：从磁盘配置推导分栏（激活模型 ≥2 → 双栏；第二栏 = 排序后第二个激活模型），
      // 不再把 aiModelTwo 重置为空 —— 打开设置时就能看到当前第二分栏模型
      const actives = cfg.models.filter((m) => (cfg.config[m]?.use_page ?? 0) !== 0);
      const primary = actives[0] ?? cfg.models[0] ?? "";
      if (primary && cfg.config[primary]) {
        loadModelIntoForm(cfg, primary);
      }
      setAiPage(actives.length >= 2 ? 2 : 1);
      setAiModelTwo(actives.length >= 2 ? actives[1] : "");
    } catch (e) {
      toast.err(`AI 配置加载失败：${e}`);
    }
    // 历史轮数（独立 ai_history.json）
    try {
      const h = await sendCommand("ai.get_history", {});
      setAiHistory(Number((h as { rounds?: number }).rounds ?? 20));
    } catch { /* 断连忽略，保持当前值 */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 把某模型配置载入表单（切模型 / 刷新共用）。只动本模型编辑字段；
  // 分栏布局（aiPage / aiModelTwo）是全局态，由 refreshAi 从配置推导，不在此重置。
  function loadModelIntoForm(cfg: AiConfig, name: string) {
    const c = cfg.config[name];
    if (!c) return;
    setAiModel(name);
    setAiAlias(c.AI_alias ?? "");
    setAiKind(c.AI_kind ?? "openai");
    setAiBaseUrl(c.AI_base_url ?? "");
    setAiApi(c.AI_API ?? "");
    setAiModelId(c.AI_model_id ?? "");
  }

  // 展开某模型行：载入其配置到编辑字段（表单跟随展开行；再次点三角收起）
  function toggleExpandModel(name: string) {
    if (expandedModel === name) {
      setExpandedModel("");
      return;
    }
    loadModelIntoForm(ai, name);
    setExpandedModel(name);
  }

  // 打开时拉数据 + 订阅变更事件自动刷新
  useEffect(() => {
    if (!open) return;
    // 打开定位：指定标签页（工具画布空态「＋」直达工具管理）+ 预选菜单栏/导航栏
    setTab(openTab);
    if (focusMenu) {
      activeMenuRef.current = focusMenu; // 先同步 ref，refreshMenus 才能保住该选择
      setActiveMenu(focusMenu);
      setActiveNav(focusNav ?? "");
    }
    consumeFocus();
    void refreshMenus();
    void refreshAi();
    void refreshTranslateCreds();
    const unMenu = subscribeEvent("menu.changed", () => { void refreshMenus(); });
    const unAi = subscribeEvent("ai.config_changed", () => { void refreshAi(); });
    return () => { unMenu(); unAi(); };
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  async function run(fn: () => Promise<unknown>, okMsg: string) {
    if (busy) return;
    setBusy(true);
    try {
      await fn();
      toast.ok(okMsg);
    } catch (e) {
      toast.err(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }

  // 连接测试：向当前模型发送 "hello"（使用输入框中的实时值，不依赖已保存配置）
  async function runAiTest() {
    setAiTesting(true);
    try {
      const r = await sendCommand("ai.test", {
        model: aiModel,
        api: aiApi,
        base_url: aiBaseUrl,
        model_id: aiModelId,
        kind: aiKind,
        alias: aiAlias,
      });
      if (r.ok) toast.ok(String(r.message ?? "响应正常"));
      else toast.err(String(r.message ?? "调用失败"));
    } catch (e) {
      toast.err(String(e instanceof Error ? e.message : e));
    } finally {
      setAiTesting(false);
    }
  }

  const TABS: { key: TabKey; label: string; icon: React.ComponentType<{ size?: number | string }> }[] = [
    { key: "tools", label: "工具管理", icon: Wrench },
    { key: "ai", label: "AI模型设置", icon: Brain },
    { key: "translate", label: "翻译设置", icon: Languages },
    { key: "shortcuts", label: "快捷键设置", icon: Keyboard },
    { key: "terminal", label: "终端设置", icon: Server },
    { key: "display", label: "菜单栏展示", icon: Eye },
    { key: "ball", label: "悬浮球", icon: CircleDot },
    { key: "update", label: "更新设置", icon: Download },
  ];

  return (
    <div className="settings-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        className={"settings-modal" + (dragging ? " is-dragging" : "") + (resizing ? " is-resizing" : "")}
        ref={panelRef}
        style={size ? { width: size.w, height: size.h } : undefined}
        role="dialog"
        aria-modal="true"
      >
        <header className="settings-modal__head" ref={headRef} {...handleProps} title="按住拖拽 / 双击复位">
          <h2 className="settings-modal__title">工具箱设置</h2>
          <button className="settings-modal__close" onClick={onClose} title="关闭 (Esc)">
            <X size={16} />
          </button>
        </header>

        <div className="settings-modal__body">
          <nav className="settings-rail">
            {TABS.map((t) => {
              const Icon = t.icon;
              return (
                <button key={t.key} className={tab === t.key ? "settings-tab active" : "settings-tab"} onClick={() => setTab(t.key)}>
                  <Icon size={14} /> {t.label}
                </button>
              );
            })}
          </nav>

          <div className="settings-content">


          {/* ================= 工具管理（菜单栏 / 导航栏 / 工具 三合一） =================
              第 1 行：菜单栏 选择 + ＋（展开新增菜单栏）+ 删除当前菜单栏
              第 2 行：导航栏 选择 + ＋（展开新增导航栏）+ 删除当前导航栏
              第 3 行起：新增工具设定（归属 = 当前所选 菜单栏/导航栏）+ 工具列表 */}
          {tab === "tools" ? (
            <div className="settings-tools">
              <h3 className="settings-sub__title">工具管理 <span className="settings-sub__hint">（菜单栏 / 导航栏 / 工具，保存即时生效）</span></h3>

              {/* 第 1 行：菜单栏选择 + ＋ + 删除 */}
              <div className="form-row">
                <label className="form-field form-field--inline">
                  <span className="form-field__label">菜单栏:</span>
                  <select
                    value={activeMenu}
                    onChange={(e) => {
                      const v = e.target.value;
                      activeMenuRef.current = v;
                      setActiveMenu(v);
                      void sendCommand("menu.list_tools", { menu: v })
                        .then((r) => setTools((r.tools ?? []) as ToolInfo[]))
                        .catch(() => setTools([]));
                      setActiveNav((menus.find((m) => m.name === v)?.navigation_bar_name ?? [])[0] ?? "");
                    }}
                  >
                    <option value="" disabled>选择菜单栏…</option>
                    {menus.map((m) => <option key={m.name} value={m.name}>{m.name}（{m.tool_count}）</option>)}
                  </select>
                </label>
                <button
                  className="form-btn"
                  onClick={() => setAddMenuOpen(!addMenuOpen)}
                  title={addMenuOpen ? "收起新增菜单栏" : "新增菜单栏"}
                >
                  <Plus size={13} />
                </button>
                <button className="form-btn" onClick={() => void refreshMenus()} title="刷新菜单 / 导航 / 工具"><RefreshCw size={13} /></button>
              </div>
              {addMenuOpen ? (
                <div className="form-row form-row--indent">
                  <input placeholder="菜单栏名称（勿用空格与特殊字符，将作为 菜单/导航 目录段）" value={menuName} onChange={(e) => setMenuName(e.target.value)} />
                  <input type="color" value={menuColor} onChange={(e) => setMenuColor(e.target.value)} title="菜单栏颜色" />
                  <button
                    className="form-btn primary"
                    disabled={busy || !menuName.trim()}
                    onClick={() => void run(
                      async () => {
                        const created = menuName.trim();
                        await sendCommand("menu.add", {
                          name: created,
                          menu_color: menuColor,
                          navigation: ["首页"],
                        });
                        setMenuName("");
                        setAddMenuOpen(false);
                        // 立即选中新增菜单栏（menu.changed 触发的 refreshMenus 读 ref，需先同步）
                        activeMenuRef.current = created;
                        setActiveMenu(created);
                        setActiveNav("首页");
                        const r = await sendCommand("menu.list_tools", { menu: created });
                        setTools((r.tools ?? []) as ToolInfo[]);
                      },
                      "菜单栏已添加（无需指定工具文件夹）"
                    )}
                  >
                    <Plus size={13} /> 添加菜单栏
                  </button>
                </div>
              ) : null}

              {/* 第 2 行：导航栏选择 + ＋ + 删除 */}
              <div className="form-row">
                <label className="form-field form-field--inline">
                  <span className="form-field__label">导航栏:</span>
                  <select value={activeNav} disabled={!activeMenu} onChange={(e) => setActiveNav(e.target.value)}>
                    <option value="">{activeMenu ? "选择导航栏…" : "请先选择菜单栏"}</option>
                    {(menus.find((m) => m.name === activeMenu)?.navigation_bar_name ?? []).map((n) => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </select>
                </label>
                <button
                  className="form-btn"
                  disabled={!activeMenu}
                  onClick={() => setAddNavOpen(!addNavOpen)}
                  title={addNavOpen ? "收起新增导航栏" : "新增导航栏"}
                >
                  <Plus size={13} />
                </button>
              </div>
              {addNavOpen ? (
                <div className="form-row form-row--indent">
                  <input placeholder="导航栏名称（如 扫描 / 提权 / 后渗透）" value={navName} onChange={(e) => setNavName(e.target.value)} />
                  <button
                    className="form-btn primary"
                    disabled={busy || !activeMenu || !navName.trim()}
                    onClick={() => void run(
                      async () => {
                        const created = navName.trim();
                        await sendCommand("menu.add_nav", { menu: activeMenu, nav: created });
                        setNavName("");
                        setAddNavOpen(false);
                        setActiveNav(created);
                      },
                      "导航栏已添加"
                    )}
                  >
                    <Plus size={13} /> 添加导航栏
                  </button>
                </div>
              ) : null}

              {/* 第 3 行起：新增工具设定（工具自动归属当前所选 菜单栏 / 导航栏）
                  第 1 行 工具名称；第 2 行 工具路径 + 右侧文件管理器按钮；第 3 行 启动方式/命令 + 添加 */}
              <div className="tools-subhead">
                <span className="settings-sub__title">新增工具</span>
                <span className="settings-sub__hint">归属：{activeMenu || "未选菜单"} / {activeNav || "首页"}</span>
              </div>
              <div className="form-row">
                <input placeholder="工具名称" value={tName} onChange={(e) => setTName(e.target.value)} />
              </div>
              <div className="form-row">
                <input
                  placeholder={isLink ? "http(s) 链接" : "工具路径（相对路径基于「菜单/导航」目录，如 test/test.exe）"}
                  value={tPath}
                  onChange={(e) => setTPath(e.target.value)}
                />
                <button
                  className="form-btn"
                  disabled={busy || isLink}
                  title={
                    isLink
                      ? "链接类工具填 http(s) 链接，无需本地文件"
                      : tRun === "文件夹打开" ? "打开文件管理器选择工具文件夹" : "打开文件管理器选择工具路径"
                  }
                  onClick={() => void pickPath()}
                >
                  <FolderOpen size={13} />
                </button>
              </div>
              <div className="form-row">
                <select value={tRun} onChange={(e) => setTRun(e.target.value)} title="启动方式">
                  {RUN_TYPES.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
                {tRun === "命令行打开" ? (
                  <input placeholder="启动命令（需带 * 占位，如 python * -h）" value={tCmd} onChange={(e) => setTCmd(e.target.value)} />
                ) : null}
                <button
                  className="form-btn primary"
                  disabled={busy || !activeMenu || !tName.trim() || !tPath.trim() || (tRun === "命令行打开" && !tCmd.includes("*"))}
                  title={tRun === "命令行打开" && !tCmd.includes("*") ? "命令行打开需带 * 占位" : `添加到「${activeMenu || "菜单"} / ${activeNav || "首页"}」`}
                  onClick={() => void run(
                    async () => {
                      await sendCommand("menu.add_tool", {
                        name: tName.trim(), path: tPath.trim(), menu: activeMenu,
                        use: activeNav || "首页", run_type: tRun, command: tCmd.trim(),
                      });
                      setTName(""); setTPath(""); setTCmd("");
                      const r = await sendCommand("menu.list_tools", { menu: activeMenu });
                      setTools((r.tools ?? []) as ToolInfo[]);
                    },
                    `工具已添加到「${activeMenu} / ${activeNav || "首页"}」`
                  )}
                >
                  <Plus size={13} /> 添加工具
                </button>
              </div>
              {!isLink && tPath.trim() && !tPath.startsWith("http") ? (
                <div className="settings-sub__hint" style={{ marginTop: 4, paddingLeft: 2 }}>
                  相对路径将存于 工具箱根/{activeMenu || "菜单"}/{activeNav || "首页"}/{tPath.trim()}（缺目录逐级创建）
                </div>
              ) : null}

              {/* 工具列表：所选菜单栏全部工具，逐条标注归属导航栏，可删除 */}
              <div className="tool-list">
                {tools.length === 0 ? <div className="menu-list__empty">该菜单栏暂无工具</div> : null}
                {tools.map((t) => (
                  <div key={t.工具名称} className="tool-item">
                    <span className="tool-item__name">{t.工具名称}</span>
                    <span className="tool-item__meta">[{t.启动方式}] {t.工具路径}</span>
                    <span className="tool-item__use">{t.nav || "首页"}</span>
                    <button
                      className="tool-item__del"
                      title="删除该工具"
                      disabled={busy}
                      onClick={() => {
                        if (!window.confirm(`删除工具「${t.工具名称}」？`)) return;
                        void run(() => sendCommand("menu.remove_tool", { menu: activeMenu, name: t.工具名称 }), `工具「${t.工具名称}」已删除`);
                      }}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {/* ================= AI模型设置（别名必填 + 动态模型） ================= */}
          {tab === "ai" ? (
            <div className="settings-ai">
              <h3 className="settings-sub__title">AI 对话模型 <span className="settings-sub__hint">（保存后立即生效，无需重启；别名必填，下拉按别名排序）</span></h3>

              {/* 模型列表：动态增删（添加表单在列表上方） */}
              <div className="ai-model-list">
                <div className="form-row">
                  <input placeholder="新模型内部名（如 gpt4o）" value={newModel} onChange={(e) => setNewModel(e.target.value)} />
                  <input placeholder="别名（必填）" value={newAlias} onChange={(e) => setNewAlias(e.target.value)} />
                  <button
                    className="form-btn primary"
                    disabled={busy || !newModel.trim() || !newAlias.trim()}
                    onClick={() => void run(
                      async () => {
                        await sendCommand("ai.add_model", { model: newModel.trim(), alias: newAlias.trim(), kind: "openai" });
                        setNewModel(""); setNewAlias("");
                      },
                      "模型已添加"
                    )}
                  >
                    <Plus size={13} /> 添加模型
                  </button>
                </div>

                {/* 会话分栏（原在各模型详情内，现固定置于「添加模型」行下方）+ 历史轮数 */}
                <div className="form-row">
                  <label className="form-field">
                    <span className="form-field__label">分栏数量:</span>
                    <select value={String(aiPage)} onChange={(e) => setAiPage(Number(e.target.value))}>
                      <option value="1">1</option>
                      <option value="2">2</option>
                    </select>
                  </label>
                  <label className="form-field">
                    <span className="form-field__label">分栏模型:</span>
                    <select value={aiModelTwo} disabled={aiPage !== 2} onChange={(e) => setAiModelTwo(e.target.value)}>
                      <option value="">{aiPage === 2 ? "选择第二个分栏模型…" : "分栏数量为 2 时启用"}</option>
                      {ai.models.filter((mm) => mm !== aiModel || mm === aiModelTwo).map((mm) => (
                        <option key={mm} value={mm}>{modelDisplay(ai, mm)}</option>
                      ))}
                    </select>
                  </label>
                  <label className="form-field" title="对话上下文保留的历史轮数（即时生效，无需重启）">
                    <span className="form-field__label">历史轮数:</span>
                    <select
                      value={String(aiHistory)}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        setAiHistory(v);
                        void run(() => sendCommand("ai.set_history", { rounds: v }), `历史轮数已设为 ${v} 轮（即时生效）`);
                      }}
                    >
                      <option value="10">10</option>
                      <option value="20">20</option>
                      <option value="50">50</option>
                      <option value="100">100</option>
                    </select>
                  </label>
                </div>
                {aiPage === 2 && !aiModelTwo ? (
                  <div className="settings-notice err">分栏数量为 2 时需选择第二个分栏模型</div>
                ) : aiPage === 2 && !!aiModelTwo && aiModelTwo === aiModel ? (
                  <div className="settings-notice err">分栏模型与当前表单模型（主分栏）相同，请切换表单模型或重选分栏模型</div>
                ) : null}
                {ai.models.map((m) => {
                  const c = ai.config[m] ?? {};
                  const inUse = (c.use_page ?? 0) !== 0;
                  const expanded = expandedModel === m;
                  return (
                    <div key={m} className={"ai-model-row" + (expanded ? " expanded" : "")}>
                      <div
                        className="ai-model-item"
                        onClick={() => toggleExpandModel(m)}
                        title="点击展开/收起该模型配置"
                      >
                        <span className="ai-model-item__name">{c.AI_alias || m}
                          {m !== (c.AI_alias || m) ? <span className="ai-model-item__key">（{m}）</span> : null}
                        </span>
                        <span className="ai-model-item__meta">
                          {inUse ? `启用${c.use_page === 2 ? "（分栏）" : ""}` : ""}
                        </span>
                        <button
                          className="ai-model-item__del"
                          title={inUse ? "启用中的模型不可删除" : "删除该模型"}
                          disabled={busy || inUse}
                          onClick={(e) => {
                            e.stopPropagation();
                            if (!window.confirm(`删除模型「${c.AI_alias || m}」？`)) return;
                            void run(() => sendCommand("ai.remove_model", { model: m }), "模型已删除");
                          }}
                        >
                          <Trash2 size={12} />
                        </button>
                        <button
                          className="ai-model-item__caret"
                          aria-label="展开配置"
                          onClick={(e) => { e.stopPropagation(); toggleExpandModel(m); }}
                        >
                          <ChevronDown size={14} className={expanded ? "rot" : ""} />
                        </button>
                      </div>

                      {/* 展开后：该模型的完整配置表单（行内，方便修改与展示） */}
                      {expanded ? (
                        <div className="ai-model-detail">
                          <div className="form-row">
                            <label className="form-field">
                              <span className="form-field__label">别名: <em className="req">*</em></span>
                              <input placeholder="该模型显示别名（必填，如 我的Kimi）" value={aiAlias} onChange={(e) => setAiAlias(e.target.value)} />
                            </label>
                          </div>
                          <div className="form-row">
                            <label className="form-field">
                              <span className="form-field__label">Base URL:</span>
                              <input placeholder="API 服务地址（可选，如 https://api.moonshot.cn/v1）" value={aiBaseUrl} onChange={(e) => setAiBaseUrl(e.target.value)} />
                            </label>
                            <label className="form-field">
                              <span className="form-field__label">模型ID:</span>
                              <input placeholder="模型名称（如 moonshot-v1-128k / glm-4 / deepseek-chat）" value={aiModelId} onChange={(e) => setAiModelId(e.target.value)} />
                            </label>
                          </div>
                          <div className="form-row">
                            <label className="form-field">
                              <span className="form-field__label">{aiKind === "ollama" ? "服务地址:" : "API 配置:"}</span>
                              <input
                                placeholder={aiKind === "ollama" ? "请输入 ollama 服务地址 (http://xxx:xxx/)" : "请输入 AI 模型的 API"}
                                value={aiApi}
                                onChange={(e) => setAiApi(e.target.value)}
                              />
                            </label>
                          </div>
                          <div className="form-row">
                            <button className="form-btn" disabled={busy || aiTesting} onClick={() => void runAiTest()} title="向当前模型发送 hello 测试连通性">
                              {aiTesting ? <RefreshCw size={13} className="spin" /> : null} 测试
                            </button>
                            <button className="form-btn" onClick={() => void refreshAi()} title="重新加载 AI 配置"><RefreshCw size={13} /> 重新加载</button>
                          </div>
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>

              {/* 保存：右下角页脚。一举两得 —— 模型信息（当前表单模型）+ 分栏布局（同一条 ai.set_config） */}
              <div className="settings-ai-footer">
                <button
                  className="form-btn primary"
                  disabled={busy || !aiModel || !aiAlias.trim() || (aiPage === 2 && !aiModelTwo) || (aiPage === 2 && !!aiModelTwo && aiModelTwo === aiModel)}
                  title={!aiModel ? "请先加载/展开模型" : !aiAlias.trim() ? "别名是必填项" : (aiPage === 2 && !aiModelTwo ? "分栏数量为 2 时请先选择第二个分栏模型" : (aiPage === 2 && !!aiModelTwo && aiModelTwo === aiModel ? "分栏模型与当前表单模型相同，请切换表单模型或重选分栏模型" : "保存当前模型信息与分栏布局（即时生效）"))}
                  onClick={() => void run(
                    () => sendCommand("ai.set_config", {
                      model: aiModel,
                      api: aiApi,
                      page_nums: aiPage,
                      model_two: aiPage === 2 ? aiModelTwo : "",
                      alias: aiAlias,
                      base_url: aiBaseUrl,
                      model_id: aiModelId,
                      kind: aiKind,
                    }),
                    aiPage === 2 ? "已保存：模型信息与双分栏布局（即时生效）" : "已保存：模型信息与单栏布局（即时生效）"
                  )}
                >
                  <Save size={13} /> 保存
                </button>
              </div>
            </div>
          ) : null}

          {/* ================= 翻译设置（百度翻译凭证：工具箱设置内直接维护，保存即生效） ================= */}
          {tab === "translate" ? (
            <div className="settings-translate">
              <h3 className="settings-sub__title">翻译设置 <span className="settings-sub__hint">（百度翻译凭证，保存于 config/bridge_secrets.json，保存即生效无需重启）</span></h3>

              <div className="form-row">
                <label className="form-field">
                  <span className="form-field__label">appid:</span>
                  <input
                    placeholder="百度翻译开放平台的 appid"
                    value={trAppId}
                    onChange={(e) => setTrAppId(e.target.value)}
                  />
                </label>
              </div>
              <div className="form-row">
                <label className="form-field">
                  <span className="form-field__label">密钥 (secretKey):</span>
                  <div className="secret-input">
                    <input
                      type="text"
                      className="secret-input__field"
                      placeholder={trRaw ? "已配置（输入新值可覆盖；留空保留当前）" : "百度翻译开放平台的密钥"}
                      value={trSecretDisplay}
                      onFocus={() => setTrSecretShown(true)}
                      onChange={(e) => { setTrSecret(e.target.value); setTrSecretTouched(true); setTrSecretShown(true); }}
                    />
                    {trRaw ? (
                      <button
                        type="button"
                        className="secret-input__eye"
                        title={trSecretShown ? "隐藏密钥（* 号）" : "显示完整密钥"}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => setTrSecretShown((s) => !s)}
                      >
                        {trSecretShown ? <EyeOff size={14} /> : <Eye size={14} />}
                      </button>
                    ) : null}
                  </div>
                </label>
              </div>

              <div className="settings-notice" role="status">
                {trConfigured
                  ? "百度凭证已配置，「汉英翻译」菜单可正常使用"
                  : "尚未配置百度凭证，「汉英翻译」菜单将提示未配置"}
              </div>

              <div className="settings-ai-footer">
                <button
                  className="form-btn"
                  disabled={busy || trTesting || !trAppId.trim()}
                  title="保存当前表单并真实调用一次百度接口验证"
                  onClick={() => void runTranslateTest()}
                >
                  {trTesting ? <RefreshCw size={13} className="spin" /> : null} 测试翻译
                </button>
                <button
                  className="form-btn primary"
                  disabled={busy || !trAppId.trim()}
                  title="保存凭证（密钥留空则保留已存值）"
                  onClick={() => void run(
                    async () => {
                      const r = await sendCommand("translate.set_creds", { app_id: trAppId, secret_key: trRaw });
                      const rr = r as { app_id?: string; secret_key_configured?: boolean };
                      setTrConfigured(!!rr.app_id && !!rr.secret_key_configured);
                      // 落盘成功：刚存值成为新的服务端现值，清空输入态，回到掩码回显
                      setTrLoadedSecret(trRaw);
                      setTrSecret("");
                      setTrSecretTouched(false);
                      setTrSecretShown(false);
                    },
                    "翻译设置已保存（即时生效）"
                  )}
                >
                  <Save size={13} /> 保存
                </button>
              </div>
            </div>
          ) : null}

          {/* ================= 快捷键设置（config/shortcuts.json 槽位→组合表；整表覆盖保存，即时生效） =================
              槽位体系：panel / dyn:菜单 / fix:菜单 / nav:n / tool:菜单__工具；
              默认组合按当前菜单顺序生成（Ctrl+N / Ctrl+Alt+N / Ctrl+Shift+N / Ctrl+Space），改键落盘 */}
          {tab === "shortcuts" ? (
            <div className="settings-shortcuts">
              <h3 className="settings-sub__title">快捷键设置 <span className="settings-sub__hint">（组合键须含 Ctrl；点组合键重新录制，点 ✕ 停用；⚠ 表示多槽位撞车，后按者先响应）</span></h3>

              <div className="sc-group">
                <div className="sc-group__title">面板</div>
                <div className="sc-row">
                  <span className="sc-row__label">回到面板</span>
                  <KeyCapture slotKey={SLOT_PANEL} dynMenus={dynNames} fixMenus={FIXED_MENUS} conflict={scConflicts.has(SLOT_PANEL)} />
                </div>
              </div>

              <div className="sc-group">
                <div className="sc-group__title">动态菜单栏（用户菜单，默认 Ctrl+N）</div>
                {menus.map((m, i) => (
                  <div className="sc-row" key={m.name}>
                    <span className="sc-row__label"><em className="sc-idx">{i + 1}</em>{m.name}</span>
                    <KeyCapture slotKey={slotDyn(m.name)} dynMenus={dynNames} fixMenus={FIXED_MENUS} conflict={scConflicts.has(slotDyn(m.name))} />
                  </div>
                ))}
              </div>

              <div className="sc-group">
                <div className="sc-group__title">固定菜单栏（系统，默认 Ctrl+Alt+N；「首页」不配快捷键——「回到面板」即可到达）</div>
                {SHORTCUT_FIX_MENUS.map((n, i) => (
                  <div className="sc-row" key={n}>
                    <span className="sc-row__label"><em className="sc-idx">{i + 1}</em>{n}</span>
                    <KeyCapture slotKey={slotFix(n)} dynMenus={dynNames} fixMenus={FIXED_MENUS} conflict={scConflicts.has(slotFix(n))} />
                  </div>
                ))}
              </div>

              <div className="sc-group">
                <div className="sc-group__title">导航栏（当前菜单下第 N 项，默认 Ctrl+Shift+N；仅当正处于某用户菜单时生效）</div>
                {Array.from({ length: 9 }, (_, i) => i + 1).map((n) => (
                  <div className="sc-row" key={n}>
                    <span className="sc-row__label"><em className="sc-idx">{n}</em>{n === 1 ? "第 1 项导航（首页）" : `第 ${n} 项导航`}</span>
                    <KeyCapture slotKey={slotNav(n)} dynMenus={dynNames} fixMenus={FIXED_MENUS} conflict={scConflicts.has(slotNav(n))} />
                  </div>
                ))}
              </div>

              <div className="sc-group">
                <div className="sc-group__title">工具快捷键（默认按列表顺序 Ctrl+Alt+1、2、3…；点组合键可自定义，✕ 停用，启动即在本机执行对应工具）</div>
                <input
                  className="sc-search"
                  placeholder="筛选：菜单 / 导航 / 工具名"
                  value={scToolQ}
                  onChange={(e) => setScToolQ(e.target.value)}
                />
                {scFiltered.length === 0 ? (
                  <div className="sc-empty">{scToolQ ? "没有匹配的工具" : "（暂无工具）"}</div>
                ) : scFiltered.map((t) => {
                  // 全局编号 = 完整列表顺序（从左到右、从上到下），不受筛选影响
                  const idx = scTools.findIndex((x) => x.menu === t.menu && x.name === t.name);
                  return (
                    <div className="sc-row" key={slotTool(t.menu, t.name)}>
                      <span className="sc-row__label" title={`${t.menu} / ${t.nav}`}>
                        {t.name} <small>{t.menu} / {t.nav}</small>
                      </span>
                      <KeyCapture
                        slotKey={slotTool(t.menu, t.name)}
                        dynMenus={dynNames}
                        fixMenus={FIXED_MENUS}
                        toolCombo={idx >= 0 ? defaultToolCombo(idx + 1) : undefined}
                        conflict={scConflicts.has(slotTool(t.menu, t.name))}
                      />
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          {/* ================= 终端设置（SSH 主机表 config/ssh_hosts.json；列表增删改，整表覆盖保存） =================
              保存后广播 ssh.hosts.changed → 导航条 SSH 下拉框即时刷新；选中别名 = 立即连接（终端管理页远端命令模式） */}
          {tab === "terminal" ? (
            <div className="settings-terminal">
              <h3 className="settings-sub__title">终端设置 <span className="settings-sub__hint">（SSH 主机保存于 config/ssh_hosts.json；导航条 SSH 下拉框选中即连接，命令在远端执行）</span></h3>

              <div className="tools-subhead">
                <span className="settings-sub__title">SSH 主机列表 {sshLoaded ? <span className="settings-sub__hint">（{sshRows.length} 台）</span> : <span className="settings-sub__hint">（加载中…）</span>}</span>
                <button className="form-btn" onClick={() => setSshRows((rows) => [...rows, emptySshRow()])} title="新增一行 SSH 主机配置">
                  <Plus size={13} /> 增加SSH主机
                </button>
              </div>

              {sshRows.map((row, i) => (
                <div className="ssh-host-row" key={i}>
                  <div className="ssh-host-row__grid">
                    <label className="form-field">
                      <span className="form-field__label">别名</span>
                      <input placeholder="如 test-srv（勿含空格，唯一）" value={row.alias} onChange={(e) => updateSshRow(i, { alias: e.target.value })} />
                    </label>
                    <label className="form-field">
                      <span className="form-field__label">地址</span>
                      <input placeholder="IP 或域名" value={row.host} onChange={(e) => updateSshRow(i, { host: e.target.value })} />
                    </label>
                    <label className="form-field">
                      <span className="form-field__label">端口</span>
                      <input placeholder="22（留空即 22）" inputMode="numeric" value={row.port} onChange={(e) => updateSshRow(i, { port: e.target.value })} />
                    </label>
                    <label className="form-field">
                      <span className="form-field__label">用户名</span>
                      <input placeholder="如 root" value={row.username} onChange={(e) => updateSshRow(i, { username: e.target.value })} />
                    </label>
                    <label className="form-field ssh-host-row__pw">
                      <span className="form-field__label">密码</span>
                      <div className="secret-input">
                        <input
                          type={row.showPw ? "text" : "password"}
                          className="secret-input__field"
                          placeholder="留空 = 走本机密钥登录"
                          value={row.password}
                          onChange={(e) => updateSshRow(i, { password: e.target.value })}
                        />
                        <button
                          type="button"
                          className="secret-input__eye"
                          title={row.showPw ? "隐藏密码" : "显示密码"}
                          onClick={() => updateSshRow(i, { showPw: !row.showPw })}
                        >
                          {row.showPw ? <EyeOff size={13} /> : <Eye size={13} />}
                        </button>
                      </div>
                    </label>
                  </div>
                  <button
                    className="ssh-host-row__del"
                    title="删除该主机"
                    disabled={sshRows.length === 1}
                    onClick={() => setSshRows((rows) => rows.filter((_, ri) => ri !== i))}
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              ))}

              <div className="settings-ai-footer">
                <span className="settings-sub__hint">保存后下拉框即时刷新；选中某台主机 = 立即连接并进入终端管理页远端模式</span>
                <button
                  className="form-btn primary"
                  disabled={sshSaving || !sshLoaded}
                  onClick={() => void saveSshHosts()}
                >
                  <Save size={13} /> {sshSaving ? "保存中…" : "保存"}
                </button>
              </div>
            </div>
          ) : null}

          {/* ================= 菜单栏展示（config.json 参数：1 显示 / 0 隐藏，即时生效） =================
              固定菜单栏 → __fixed_menu_visible__ 保留键；用户菜单栏 → 各菜单项 menu_visible */}
          {tab === "display" ? (
            <div className="settings-display">
              <h3 className="settings-sub__title">菜单栏展示 <span className="settings-sub__hint">（参数 1 显示 / 0 隐藏，保存于 config.json，即时生效）</span></h3>

              <div className="menu-vis-group">
                <div className="menu-vis-group__title">系统固定菜单栏</div>
                {FIXED_MENUS.map((n) => (
                  <label key={n} className="menu-vis-row">
                    <input
                      type="checkbox"
                      checked={(fixedVis[n] ?? 1) !== 0}
                      onChange={(e) => void run(
                        () => sendCommand("menu.set_fixed_visible", { name: n, visible: e.target.checked }),
                        `菜单栏「${n}」已${e.target.checked ? "显示" : "隐藏"}`
                      )}
                    />
                    <span className="menu-vis-row__name">{n}</span>
                    <span className="menu-vis-row__hint">visible = {(fixedVis[n] ?? 1) ? 1 : 0}</span>
                  </label>
                ))}
              </div>

              <div className="menu-vis-group">
                <div className="menu-vis-group__title">用户菜单栏</div>
                {menus.length === 0 ? <div className="menu-list__empty">暂无菜单栏（先到「工具管理」添加）</div> : null}
                {menus.map((m) => (
                  <label key={m.name} className="menu-vis-row">
                    <input
                      type="checkbox"
                      checked={(m.menu_visible ?? 1) !== 0}
                      onChange={(e) => void run(
                        () => sendCommand("menu.set_visible", { name: m.name, visible: e.target.checked }),
                        `菜单栏「${m.name}」已${e.target.checked ? "显示" : "隐藏"}`
                      )}
                    />
                    <span className="menu-vis-row__name">{m.name}</span>
                    <span className="menu-vis-row__hint">{m.tool_count} 个工具 · menu_visible = {(m.menu_visible ?? 1) ? 1 : 0}</span>
                  </label>
                ))}
              </div>
            </div>
          ) : null}

          {/* ================= 悬浮球（原生置顶小球：置顶开关 + 隐藏开关；原生球不可用时仅提示） =================
              状态源 config/ball_pos.json（bridge 持久化）；变更广播 ball.state 实时同步 */}
          {tab === "ball" ? (
            <div className="settings-display">
              <h3 className="settings-sub__title">悬浮球 <span className="settings-sub__hint">（页面内小球随时可用；原生置顶小球由 bridge 进程运行，可最小化共存）</span></h3>

              {!ballAvail ? (
                <div className="menu-list__empty">原生悬浮球当前不可用（bridge 未运行 / 依赖缺失），设置保存后 bridge 重启时生效。</div>
              ) : (
                <>
                  <div className="menu-vis-group">
                    <div className="menu-vis-group__title">显示与层级</div>
                    <label className="menu-vis-row">
                      <input
                        type="checkbox"
                        checked={ballTop}
                        onChange={(e) => void run(
                          () => sendCommand("ball.set_topmost", { on: e.target.checked }),
                          `悬浮球${e.target.checked ? "已置顶在最前" : "已取消置顶"}`
                        )}
                      />
                      <span className="menu-vis-row__name">置顶在最前</span>
                      <span className="menu-vis-row__hint">小球始终浮于其他窗口之上</span>
                    </label>
                    <label className="menu-vis-row">
                      <input
                        type="checkbox"
                        checked={ballHidden}
                        onChange={(e) => void run(
                          () => sendCommand("ball.set_hidden", { hidden: e.target.checked }),
                          e.target.checked ? "悬浮球已隐藏" : "悬浮球已显示"
                        )}
                      />
                      <span className="menu-vis-row__name">隐藏悬浮球</span>
                      <span className="menu-vis-row__hint">隐藏后可在托盘「显示悬浮球」或取消勾选恢复</span>
                    </label>
                  </div>

                  <div className="menu-vis-group">
                    <div className="menu-vis-group__title">操作提示</div>
                    <div className="menu-vis-row">
                      <span className="menu-vis-row__hint" style={{ flex: 1 }}>
                        原生小球：左键打开工具箱 · 拖动换位 · 右键弹出菜单（隐藏 / 置顶·取消置顶 / 关闭）
                      </span>
                    </div>
                  </div>
                </>
              )}
            </div>
          ) : null}

          {/* ================= 更新设置（GitHub 检查更新 + 工具箱介绍/点赞 + 版本更新记录） =================
              检查更新：update.check 对比本地版本与仓库 latest Release；仓库地址存 config/update.json */}
          {tab === "update" ? (
            <div className="settings-update">
              <h3 className="settings-sub__title">检查更新 <span className="settings-sub__hint">（请求 GitHub 仓库最新 Release，与本地版本对比）</span></h3>

              <div className="form-row">
                <input
                  placeholder="GitHub 仓库地址（owner/repo，如 myuser/daybreak-toolbox；留空 = 未配置）"
                  value={upRepo}
                  onChange={(e) => setUpRepo(e.target.value)}
                />
                <button className="form-btn" onClick={() => void saveUpRepo()} title="保存仓库地址到 config/update.json">
                  <Save size={13} /> 保存仓库
                </button>
                <button
                  className="form-btn primary"
                  disabled={upChecking || !upRepo.trim()}
                  title={!upRepo.trim() ? "先配置并保存 GitHub 仓库地址" : "检查 GitHub 是否有新版本"}
                  onClick={() => void checkUpdate()}
                >
                  {upChecking ? <RefreshCw size={13} className="spin" /> : <Download size={13} />} 检查更新
                </button>
              </div>

              {upResult.kind !== "idle" ? (
                <div className={`up-status up-status--${upResult.kind}`}>
                  {upResult.kind === "update" ? (
                    <>
                      <span>{upResult.msg}</span>
                      {upResult.url ? (
                        <a className="up-status__link" href={upResult.url} target="_blank" rel="noreferrer">查看更新内容 →</a>
                      ) : null}
                    </>
                  ) : (
                    <span>{upResult.msg}</span>
                  )}
                </div>
              ) : null}

              {/* 工具箱介绍 + GitHub 点赞推荐 */}
              <div className="update-intro">
                <div className="update-intro__badge">破晓 · 工具箱</div>
                <p className="update-intro__text">
                  Daybreak Toolbox 是一款面向 Windows 渗透测试的工具箱：菜单栏/导航栏/工具全可配置，
                  内置 AI 对话、汉英翻译、编解码、终端管理（本地 + SSH 远端主机）、临时笔记与全局快捷键，
                  本地运行、数据不出机器。若觉得好用，欢迎去 GitHub 点个 Star 支持持续更新！
                </p>
                <div className="update-intro__star">
                  {upRepo.trim() ? (
                    <a
                      className="update-star"
                      href={`https://github.com/${upRepo.trim()}`}
                      target="_blank"
                      rel="noreferrer"
                      title="在新标签页打开仓库并点赞（Star）"
                    >
                      <Star size={15} /> 去 GitHub 点赞
                    </a>
                  ) : (
                    <span className="settings-sub__hint">配置并保存上方的 GitHub 仓库地址后，可在此点赞</span>
                  )}
                </div>
              </div>

              {/* 版本更新记录（历史静态数据） */}
              <AboutDialog />
            </div>
          ) : null}
          </div>
        </div>
        {/* 右下角拉伸把手（min 680x420 / max 1600x1000，且不超过视口） */}
        <div
          className={"resize-grip" + (resizing ? " is-resizing" : "")}
          onPointerDown={onResizeStart}
          title="拖动拉伸（最小 680x420）"
        />
      </div>
    </div>
  );
}
