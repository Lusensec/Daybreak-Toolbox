import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useNavigate } from "react-router";
import { X, Plus, Trash2, Pencil, Maximize2, Minimize2, RefreshCw, FolderOpen, Eye, Wrench, Keyboard, Download, Star, Menu, List, Settings, Sun, Moon, Monitor } from "lucide-react";
import { sendCommand, subscribeEvent } from "../services/ws";
import { AboutDialog } from "./AboutDialog";
import { useToast } from "./toast";
import { useSettingsModal } from "../store/settingsModal";
import { useMenuStore } from "../features/menu/store";
import { useTheme } from "../theme/ThemeProvider";
import type { ThemeChoice } from "../theme/ThemeProvider";
import { promptOpen, usePromptStore } from "./PromptDialog";
import { FIXED_MENUS } from "../features/menu/fixedMenus";
import { useDraggable } from "../hooks/useDraggable";
import { useResize } from "../hooks/useResize";
import { KeyCapture } from "../features/shortcuts/KeyCapture";
import { useShortcutsStore } from "../features/shortcuts/store";
import { findConflicts, SLOT_PANEL, defaultToolCombo, slotDyn, slotNav, slotTool } from "../features/shortcuts/shortcuts";
import "./SettingsModal.css";

export type TabKey = "general" | "menus" | "navs" | "tools" | "display" | "shortcuts" | "update";

/** 更新检查的固定 GitHub 仓库（「更新设置」已无仓库配置 UI；
 *  必须与 bridge/update_service.DEFAULT_REPO 保持一致 —— 后端回退链的最终兜底）。 */
const UPDATE_REPO = "Lusensec/Daybreak-Toolbox";

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

// 工具管理提供的启动方式（按需求去掉「下载链接」；后端仍兼容历史数据）
const RUN_TYPES = ["直接打开", "命令行打开", "文件夹打开", "链接打开"];

/**
 * 工具箱设置模态框（可拖拽/单向拉伸，右侧按钮 / 首页卡 点击打开）。
 * 标签页：
 *  通用设置（默认打开页） → 菜单栏管理 → 导航栏管理 → 工具管理 → 菜单栏展示 → 快捷键设置 → 更新检查
 *  - 菜单栏管理页：菜单栏列表（行点击选中 / 改名 / 删除）+ 新增菜单栏行
 *  - 导航栏管理页：菜单栏下拉（选归属）+ 导航列表（行点击选中 / 改名 / 删除）+ 新增导航行
 *  - 工具管理页：菜单/导航 双下拉 + 新增表单 + 按导航过滤列表；改名删除亦可走顶栏右键菜单
 * 数据刷新：订阅 menu.changed 自动重载。
 * v2.1.3：AI 模型设置 / 翻译设置 / 终端设置 三个页签随对应功能面板一并移除。
 */
export function SettingsModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [tab, setTab] = useState<TabKey>("general");
  const navigate = useNavigate();

  // 通用设置：主题（与顶栏主题循环按钮共用 ThemeProvider，立即生效 + 本地持久化）
  const { theme, set: setTheme } = useTheme();
  const THEME_CHOICES: { v: ThemeChoice; label: string; icon: React.ComponentType<{ size?: number | string }> }[] = [
    { v: "light", label: "浅色", icon: Sun },
    { v: "dark", label: "深色", icon: Moon },
    { v: "system", label: "跟随系统", icon: Monitor },
  ];
  // v2.0.15「关闭后进入最小化」：桥接侧共享偏好（config/settings.json），开启后
  // 顶栏 X / Alt+F4 → 最小化驻留托盘（托盘菜单唤回），而非退出进程；切换即时生效无需重启
  const [closeToTray, setCloseToTray] = useState<boolean | null>(null);
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

  // 单向拉伸锚点：首次拖把手时捕获面板左上角（视口坐标）并切到 position:fixed 定位。
  // 居中模式下改 width/height 会被 flex 重新居中 → 四周对称扩张；钉住左上角后
  // 拉伸只向右下延伸（单侧），手势结束后保持钉住位置。
  const [pin, setPin] = useState<{ left: number; top: number } | null>(null);
  const onGripPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!pin && panelRef.current) {
      const r = panelRef.current.getBoundingClientRect();
      setPin({ left: r.left, top: r.top });
    }
    onResizeStart(e);
  };

  // 全屏开关（⛶ 按钮 / 标题栏双击，同子窗口）：面板铺满整个视口（100vw×100vh，随窗口 resize 自动跟随）；
  // 进出全屏不改 pin/size → 退出后自动回到全屏前的布局（居中/钉住/尺寸原样）
  const [fs, setFs] = useState(false);

  // 标题栏：双击 = 全屏/还原（替代原「双击复位」——退出全屏即回到全屏前布局）；
  // 全屏中禁拖（整窗即视口，无移动意义）
  const headProps = {
    onPointerDown: (e: React.PointerEvent<HTMLElement>) => { if (!fs) handleProps.onPointerDown(e); },
    onDoubleClick: () => setFs((v) => !v),
  };

  // ---- 工具管理状态（菜单栏/导航栏/工具 三合一）----
  const [menus, setMenus] = useState<MenuInfo[]>([]);
  const [menuName, setMenuName] = useState("");
  const [menuColor, setMenuColor] = useState("#2980b9");
  const [navName, setNavName] = useState("");
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [activeMenu, setActiveMenu] = useState("");
  const [activeNav, setActiveNav] = useState("");          // 当前工具归属的导航栏（工具使用 字段）
  // 最新所选菜单栏（ref 镜像）：menu.changed 订阅回调闭包会过期，刷新时读 ref 保住用户选择
  const activeMenuRef = useRef(activeMenu);
  useEffect(() => { activeMenuRef.current = activeMenu; }, [activeMenu]);
  const [tName, setTName] = useState("");
  const [tPath, setTPath] = useState("");
  const [tRun, setTRun] = useState(RUN_TYPES[0]);
  const [tCmd, setTCmd] = useState("");
  const isLink = tRun === "链接打开" || tRun === "下载链接"; // 链接类：路径为 http(s)，不弹文件管理器
  // 当前菜单的导航栏名列表（② 段列表数据源）
  const activeNavs = menus.find((m) => m.name === activeMenu)?.navigation_bar_name ?? [];
  // ③ 段工具列表：按当前导航过滤（未选导航时显示全量并标注归属）
  const visibleTools = activeNav ? tools.filter((t) => (t.nav ?? "首页") === activeNav) : tools;

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

  // ---- 工具管理三段化选中联动（①② 段下拉框切换；后端广播 menu.changed → refreshMenus 自动刷新）----

  /** 选中菜单（下拉）：②③ 段随之联动；ref 同步保证随后的 menu.changed 刷新保住选择 */
  function selectMenu(m: MenuInfo) {
    activeMenuRef.current = m.name;
    setActiveMenu(m.name);
    setActiveNav(m.navigation_bar_name[0] ?? "");
    void sendCommand("menu.list_tools", { menu: m.name })
      .then((r) => setTools((r.tools ?? []) as ToolInfo[]))
      .catch(() => setTools([]));
  }

  /** 选中导航（下拉/列表行点击）：③ 段工具列表按此过滤 */
  function selectNav(n: string) {
    setActiveNav(n);
  }

  /** 菜单栏行改名：全局重命名对话框 → menu.rename；改名前同步 ref（menu.changed 刷新保住对新名的选择） */
  async function renameMenuRow(name: string) {
    const nn = await promptOpen(`重命名菜单栏「${name}」`, name);
    if (nn === null) return;
    activeMenuRef.current = nn;
    try {
      await sendCommand("menu.rename", { name, new_name: nn });
      toast.ok(`菜单栏已改名为「${nn}」`);
    } catch (e) {
      toast.err(`改名失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }

  /** 菜单栏行删除：二次确认（含级联工具数）→ menu.remove（连同全部工具） */
  async function deleteMenuRow(name: string) {
    const cnt = menus.find((m) => m.name === name)?.tool_count ?? 0;
    if (!window.confirm(`删除菜单栏「${name}」${cnt ? `及其 ${cnt} 个工具` : ""}？`)) return;
    if (activeMenu === name) activeMenuRef.current = "";
    try {
      await sendCommand("menu.remove", { name });
      toast.ok(`菜单栏「${name}」已删除`);
    } catch (e) {
      toast.err(`删除失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }

  /** 导航栏行改名：全局重命名对话框 → menu.rename_nav（参数名 new_name） */
  async function renameNavRow(nav: string) {
    if (!activeMenu) return;
    const nn = await promptOpen(`重命名导航栏「${nav}」（菜单「${activeMenu}」）`, nav);
    if (nn === null) return;
    try {
      await sendCommand("menu.rename_nav", { menu: activeMenu, nav, new_name: nn });
      setActiveNav(nn);
      toast.ok(`导航栏已改名为「${nn}」`);
    } catch (e) {
      toast.err(`改名失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }

  /** 导航栏行删除：二次确认（含该导航工具数）→ menu.remove_nav（级联删工具） */
  async function deleteNavRow(nav: string) {
    if (!activeMenu) return;
    const cnt = tools.filter((t) => (t.nav ?? "首页") === nav).length;
    if (!window.confirm(`删除导航栏「${nav}」${cnt ? `及其 ${cnt} 个工具` : ""}？`)) return;
    try {
      await sendCommand("menu.remove_nav", { menu: activeMenu, nav });
      if (activeNav === nav) setActiveNav("");
      toast.ok(`导航栏「${nav}」已删除`);
    } catch (e) {
      toast.err(`删除失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }

  /** 导航行的工具数（当前菜单的 tools 按 nav 分组） */
  function navToolCount(n: string): number {
    return tools.filter((t) => (t.nav ?? "首页") === n).length;
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

  // ---- 更新设置状态（检查更新结果；仓库不再可配置——固定检查 UPDATE_REPO，
  //      与 bridge/update_service.DEFAULT_REPO 同值，后端回退链兜底）----
  const [upChecking, setUpChecking] = useState(false);
  type UpAsset = { name: string; size: number; download_url: string };
  type UpResult =
    | { kind: "idle" }
    | { kind: "ok"; msg: string }
    | { kind: "update"; msg: string; url: string; asset: UpAsset | null; platform: string }
    | { kind: "err"; msg: string };
  const [upResult, setUpResult] = useState<UpResult>({ kind: "idle" });
  // v2.2.4：程序内下载安装（进度经 SSE update.progress 推送；下载完成后启动静默安装）
  const [upDownloading, setUpDownloading] = useState(false);
  const [upPercent, setUpPercent] = useState(0);
  const [upPath, setUpPath] = useState("");
  const [upInstalling, setUpInstalling] = useState(false);

  async function checkUpdate() {
    setUpChecking(true);
    setUpPath("");
    setUpDownloading(false);
    setUpPercent(0);
    try {
      const r = await sendCommand("update.check", {});
      if (r.has_update) {
        // 取可自动安装的 Windows 资产（后端按命名约定筛选；非 win 平台仅给链接）
        let asset: UpAsset | null = null;
        let platform = "";
        try {
          const [pick, env] = await Promise.all([
            sendCommand("update.pick_asset", {}) as Promise<{ asset?: UpAsset | null }>,
            sendCommand("app.env", {}) as Promise<{ platform?: string }>,
          ]);
          asset = pick.asset ?? null;
          platform = String(env.platform ?? "");
        } catch { /* 取资产失败则退化为「查看更新内容」链接 */ }
        setUpResult({
          kind: "update",
          msg: `发现新版本 ${String(r.latest_version)}（当前 ${String(r.local_version)}）`,
          url: String(r.release_url ?? ""), asset, platform,
        });
      } else {
        setUpResult({ kind: "ok", msg: `已是最新版本 ${String(r.local_version)}${r.latest_version ? `（GitHub 最新 ${String(r.latest_version)}）` : ""}` });
      }
    } catch (e) {
      setUpResult({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    } finally {
      setUpChecking(false);
    }
  }

  /** 一键下载：update.download 内部走阻塞下载 + SSE 进度；完成后更新路径，展示「立即安装」。 */
  async function startDownload() {
    if (upResult.kind !== "update" || !upResult.asset) return;
    setUpDownloading(true);
    setUpPercent(0);
    try {
      // 后端下载走后台线程 + SSE 进度，本命令立即返回（不受默认 15s 超时限制）
      await sendCommand("update.download", { asset: upResult.asset });
    } catch (e) {
      setUpDownloading(false);
      toast.err(`下载失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }

  /** 立即安装：启动 Inno 静默安装后应用自动退出（让安装程序接管旧文件）。 */
  async function startInstall() {
    if (!upPath) return;
    setUpInstalling(true);
    try {
      const r = await sendCommand("update.install", { path: upPath }) as { message?: string };
      toast.ok(r.message ?? "安装程序已启动，应用即将退出以完成更新");
    } catch (e) {
      setUpInstalling(false);
      toast.err(`安装失败：${e instanceof Error ? e.message : String(e)}`);
    }
  }

  // 订阅下载进度（模态打开期间）
  useEffect(() => {
    if (!open) return;
    const un = subscribeEvent("update.progress", (raw) => {
      const p = raw as { phase?: string; percent?: number; path?: string; message?: string };
      if (p.phase === "downloading") {
        setUpPercent(Math.max(0, Math.min(100, p.percent ?? 0)));
      } else if (p.phase === "downloaded") {
        setUpDownloading(false);
        setUpPercent(100);
        setUpPath(String(p.path ?? ""));
        toast.ok("安装包已下载完成，点「立即安装」完成更新");
      } else if (p.phase === "error") {
        setUpDownloading(false);
        toast.err(p.message ?? "下载失败");
      }
    });
    return un;
  }, [open]);

  const refreshMenus = useCallback(async () => {
    try {
      const r = await sendCommand("menu.list", {});
      const list = (r.menus ?? []) as MenuInfo[];
      setMenus(list);
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
    const unMenu = subscribeEvent("menu.changed", () => { void refreshMenus(); });
    return unMenu;
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  // Esc 关闭（全局重命名对话框打开时由其独占 Esc，不连带关掉设置框）
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (usePromptStore.getState().resolve) return;
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // 关闭时清掉单向拉伸锚点（pin 是视口坐标，跨次打开残留会漂到旧位置）
  useEffect(() => { if (!open) setPin(null); }, [open]);

  // v2.0.15：打开模态时加载「关闭后进入最小化」当前值（settings.get）
  useEffect(() => {
    if (!open) return;
    sendCommand("settings.get", {})
      .then((r) => setCloseToTray(Boolean((r as { close_to_tray?: boolean }).close_to_tray)))
      .catch(() => setCloseToTray(false));
  }, [open]);

  if (!open) return null;

  async function run(fn: () => Promise<unknown>, okMsg: string): Promise<boolean> {
    if (busy) return false;
    setBusy(true);
    try {
      await fn();
      toast.ok(okMsg);
      return true;
    } catch (e) {
      toast.err(String(e instanceof Error ? e.message : e));
      return false;
    } finally {
      setBusy(false);
    }
  }

  /** v2.2.4：关闭行为单选切换（close_to_tray 存桥接侧 config/settings.json，即时生效） */
  async function setCloseBehavior(next: boolean) {
    if (closeToTray === next) return;
    await run(async () => {
      await sendCommand("settings.set", { close_to_tray: next });
      setCloseToTray(next);
    }, next
      ? "已设为：关闭窗口时最小化到托盘（托盘菜单可唤回）"
      : "已设为：关闭窗口时退出程序");
  }

  const TABS: { key: TabKey; label: string; icon: React.ComponentType<{ size?: number | string }> }[] = [
    { key: "general", label: "通用设置", icon: Settings },
    { key: "menus", label: "菜单栏管理", icon: Menu },
    { key: "navs", label: "导航栏管理", icon: List },
    { key: "tools", label: "工具管理", icon: Wrench },
    { key: "display", label: "菜单栏展示", icon: Eye },
    { key: "shortcuts", label: "快捷键设置", icon: Keyboard },
    { key: "update", label: "更新检查", icon: Download },
  ];

  return (
    <div className="settings-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        className={"settings-modal" + (dragging ? " is-dragging" : "") + (resizing ? " is-resizing" : "") + (fs ? " is-fs" : "")}
        ref={panelRef}
        style={fs
          ? { position: "fixed", left: 0, top: 0, width: "100vw", height: "100vh" }
          : pin
            ? { position: "fixed", left: pin.left, top: pin.top, width: size?.w ?? 960, height: size?.h ?? 580 }
            : size ? { width: size.w, height: size.h } : undefined}
        role="dialog"
        aria-modal="true"
      >
        <header className="settings-modal__head" ref={headRef} {...headProps}
          title={fs ? "双击 退出全屏" : "按住拖拽 / 双击 全屏"}>
          <h2 className="settings-modal__title">工具箱设置</h2>
          <span className="settings-modal__head-btns">
            <button
              className="settings-modal__full"
              title={fs ? "退出全屏" : "全屏"}
              onClick={() => setFs((v) => !v)}
            >
              {fs ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            </button>
            <button className="settings-modal__close" onClick={onClose} title="关闭 (Esc)">
              <X size={16} />
            </button>
          </span>
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


          {/* ================= 通用设置页（默认打开页；基础设置：当前 主题，后续逐步增加） ================= */}
          {tab === "general" ? (
            <div className="settings-display">
              <h3 className="settings-sub__title">通用设置 <span className="settings-sub__hint">（基础设置，后续将逐步增加更多项）</span></h3>

              <div className="menu-vis-group">
                <div className="menu-vis-group__title">外观</div>
                <div className="form-row">
                  {THEME_CHOICES.map((t) => {
                    const TIcon = t.icon;
                    return (
                      <button
                        key={t.v}
                        type="button"
                        className={"form-btn" + (theme === t.v ? " primary" : "")}
                        title={theme === t.v ? "当前主题" : `切换为${t.label}`}
                        onClick={() => setTheme(t.v)}
                      >
                        <TIcon size={13} /> {t.label}
                      </button>
                    );
                  })}
                  <span className="settings-sub__hint">切换即时生效，选择保存在本地（刷新保持）</span>
                </div>
              </div>

              <div className="menu-vis-group">
                <div className="menu-vis-group__title">窗口</div>
                {/* v2.2.4：关闭行为改为单选组 —— 退出程序 / 最小化到托盘（互斥，即时生效） */}
                <div className="radio-group" role="radiogroup" aria-label="关闭窗口时的行为">
                  <label className={"radio-opt" + (closeToTray === false ? " is-active" : "")}>
                    <input
                      type="radio" name="close-behavior"
                      checked={closeToTray === false}
                      disabled={busy || closeToTray === null}
                      onChange={() => void setCloseBehavior(false)}
                    />
                    <X size={13} /> <span>关闭时退出程序</span>
                  </label>
                  <label className={"radio-opt" + (closeToTray === true ? " is-active" : "")}>
                    <input
                      type="radio" name="close-behavior"
                      checked={closeToTray === true}
                      disabled={busy || closeToTray === null}
                      onChange={() => void setCloseBehavior(true)}
                    />
                    <Minimize2 size={13} /> <span>关闭时最小化到托盘</span>
                  </label>
                </div>
                <span className="settings-sub__hint">
                  选择「最小化到托盘」后，点顶栏「关闭（×）」或 Alt+F4 时窗口最小化并驻留托盘（托盘菜单「打开…」可重新唤回）；「退出破晓工具箱」为真正的退出。切换即时生效。
                </span>
              </div>
            </div>
          ) : null}

          {/* ================= 菜单栏管理页（新增菜单栏行（列表上方） + 菜单栏列表：行点击选中 / 改名 / 删除） ================= */}
          {tab === "menus" ? (
            <div className="settings-tools">
              <h3 className="settings-sub__title">菜单栏管理 <span className="settings-sub__hint">（点行选中；✎ 改名 / 🗑 删除连同其下全部工具；保存即时生效）</span></h3>
              <div className="form-row form-row--indent">
                <input placeholder="新增菜单栏名称（勿用空格与特殊字符，将作为 菜单/导航 目录段）" value={menuName} onChange={(e) => setMenuName(e.target.value)} />
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
              <div className="mgmt-list">
                {menus.length === 0 ? <div className="menu-list__empty">暂无菜单栏（在上方添加）</div> : null}
                {menus.map((m) => (
                  <div
                    key={m.name}
                    className={"mgmt-row" + (activeMenu === m.name ? " is-active" : "")}
                    title="点击选中该菜单栏（导航栏管理 / 工具管理页随之一同联动）"
                    onClick={() => selectMenu(m)}
                  >
                    <span className="mgmt-row__dot" style={{ background: m.menu_color }} />
                    <span className="mgmt-row__name">{m.name}</span>
                    <span className="mgmt-row__meta">{m.tool_count} 个工具</span>
                    <button
                      className="mgmt-row__btn"
                      title="改名菜单栏"
                      disabled={busy}
                      onClick={(e) => { e.stopPropagation(); void renameMenuRow(m.name); }}
                    >
                      <Pencil size={12} />
                    </button>
                    <button
                      className="mgmt-row__btn"
                      title="删除菜单栏（连同其下全部工具）"
                      disabled={busy}
                      onClick={(e) => { e.stopPropagation(); void deleteMenuRow(m.name); }}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* ================= 导航栏管理页（菜单栏下拉选归属 + 新增导航行（列表上方） + 导航列表：行点击选中 / 改名 / 删除） ================= */}
          {tab === "navs" ? (
            <div className="settings-tools">
              <h3 className="settings-sub__title">导航栏管理 <span className="settings-sub__hint">（选归属菜单栏后查看/管理该菜单的导航；点行选中，✎ 改名 / 🗑 删除连同其下工具）</span></h3>
              <div className="form-row">
                <label className="form-field form-field--inline">
                  <span className="form-field__label">菜单栏:</span>
                  <select
                    value={activeMenu}
                    onChange={(e) => {
                      const m = menus.find((x) => x.name === e.target.value);
                      if (m) selectMenu(m);
                    }}
                  >
                    <option value="" disabled>选择菜单栏…</option>
                    {menus.map((m) => <option key={m.name} value={m.name}>{m.name}（{m.tool_count}）</option>)}
                  </select>
                </label>
              </div>
              <div className="form-row form-row--indent">
                <input placeholder="新增导航栏名称（归属上方所选菜单栏；如 扫描 / 提权 / 后渗透）" value={navName} onChange={(e) => setNavName(e.target.value)} disabled={!activeMenu} />
                <button
                  className="form-btn primary"
                  disabled={busy || !activeMenu || !navName.trim()}
                  onClick={() => void run(
                    async () => {
                      const created = navName.trim();
                      await sendCommand("menu.add_nav", { menu: activeMenu, nav: created });
                      setNavName("");
                      setActiveNav(created);
                    },
                    "导航栏已添加"
                  )}
                >
                  <Plus size={13} /> 添加导航栏
                </button>
              </div>
              <div className="mgmt-list">
                {!activeMenu
                  ? <div className="menu-list__empty">先在上方选择菜单栏</div>
                  : activeNavs.length === 0
                    ? <div className="menu-list__empty">该菜单下暂无导航栏（在上方添加）</div>
                    : null}
                {activeNavs.map((n) => (
                  <div
                    key={n}
                    className={"mgmt-row" + (activeNav === n ? " is-active" : "")}
                    title="点击选中该导航栏（工具管理页工具列表随之过滤）"
                    onClick={() => selectNav(n)}
                  >
                    <span className="mgmt-row__name">{n}</span>
                    <span className="mgmt-row__meta">{navToolCount(n)} 个工具</span>
                    <button
                      className="mgmt-row__btn"
                      title="改名导航栏"
                      disabled={busy}
                      onClick={(e) => { e.stopPropagation(); void renameNavRow(n); }}
                    >
                      <Pencil size={12} />
                    </button>
                    <button
                      className="mgmt-row__btn"
                      title="删除导航栏（连同其下工具）"
                      disabled={busy}
                      onClick={(e) => { e.stopPropagation(); void deleteNavRow(n); }}
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* ================= 工具管理页（菜单/导航 双下拉选归属 + 新增工具表单 + 按导航过滤工具列表） =================
              所有写操作后后端广播 menu.changed → 本标签订阅 refreshMenus 自动刷新（读 ref 保选择） */}
          {tab === "tools" ? (
            <div className="settings-tools">
              <div className="tools-subhead">
                <span className="settings-sub__title">工具管理</span>
                <span className="settings-sub__hint">归属：{activeMenu || "未选菜单"} / {activeNav || "首页"}（工具列表按当前导航过滤）</span>
              </div>
              <div className="form-row">
                <label className="form-field form-field--inline">
                  <span className="form-field__label">菜单栏:</span>
                  <select
                    value={activeMenu}
                    onChange={(e) => {
                      const m = menus.find((x) => x.name === e.target.value);
                      if (m) selectMenu(m);
                    }}
                  >
                    <option value="" disabled>选择菜单栏…</option>
                    {menus.map((m) => <option key={m.name} value={m.name}>{m.name}（{m.tool_count}）</option>)}
                  </select>
                </label>
                <label className="form-field form-field--inline">
                  <span className="form-field__label">导航栏:</span>
                  <select value={activeNav} disabled={!activeMenu} onChange={(e) => selectNav(e.target.value)}>
                    <option value="">{activeMenu ? "选择导航栏…" : "请先选择菜单栏"}</option>
                    {activeNavs.map((n) => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </select>
                </label>
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
                      // v2.2.0：主动拉一次全局菜单/工具数据（menu.changed 事件是异步的，
                      // 这里先刷新保证关闭弹框后顶栏/左侧栏已是新数据）
                      await useMenuStore.getState().refresh();
                      const r = await sendCommand("menu.list_tools", { menu: activeMenu });
                      setTools((r.tools ?? []) as ToolInfo[]);
                    },
                    `工具已添加到「${activeMenu} / ${activeNav || "首页"}」`
                  ).then((ok) => {
                    // v2.2.0：添加成功后收起设置弹框、把该菜单上架到顶栏并直接打开该导航画布
                    if (!ok) return;
                    const menu = activeMenu, nav = activeNav || "首页";
                    const st = useMenuStore.getState();
                    st.pinMenu(menu);
                    st.openToolCanvas(menu, nav);
                    onClose();
                    navigate(`/tools/${encodeURIComponent(menu)}/${encodeURIComponent(nav)}`);
                  })}
                >
                  <Plus size={13} /> 添加工具
                </button>
              </div>
              {!isLink && tPath.trim() && !tPath.startsWith("http") ? (
                <div className="settings-sub__hint" style={{ marginTop: 4, paddingLeft: 2 }}>
                  相对路径将存于 工具箱根/{activeMenu || "菜单"}/{activeNav || "首页"}/{tPath.trim()}（缺目录逐级创建）
                </div>
              ) : null}

              {/* 工具列表：按当前导航过滤（未选导航时全量），逐条标注归属导航，可删除 */}
              <div className="tool-list">
                {visibleTools.length === 0
                  ? <div className="menu-list__empty">{activeNav ? `「${activeNav}」下暂无工具（在上方添加，或用「导航栏:」下拉切换导航）` : "该菜单栏暂无工具（在上方添加）"}</div>
                  : (
                    <div className="settings-sub__hint" style={{ marginBottom: 6 }}>
                      {activeNav ? `当前显示「${activeNav}」的 ${visibleTools.length} 个工具（用「导航栏:」下拉可切换导航）` : `全部 ${visibleTools.length} 个工具`}
                    </div>
                  )}
                {visibleTools.map((t) => (
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


          {/* ================= 快捷键设置（config/shortcuts.json 槽位→组合表；整表覆盖保存，即时生效） =================
              槽位体系：panel / dyn:菜单 / fix:菜单 / nav:n / tool:菜单__工具；
              默认组合按当前菜单顺序生成（Ctrl+N / Ctrl+Alt+N / Ctrl+Shift+N / Ctrl+Space），改键落盘 */}
          {tab === "shortcuts" ? (
            <div className="settings-shortcuts">
              <h3 className="settings-sub__title">快捷键设置 <span className="settings-sub__hint">（任意键或组合键均可，Ctrl 非必须；点按键重新录制，点 ✕ 停用；⚠ 表示多槽位撞车，后按者先响应）</span></h3>

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

          {/* ================= 菜单栏展示（config.json 参数：1 显示 / 0 隐藏，即时生效） =================
              v2.1.3：系统固定菜单栏已移除（固定入口只剩首页，不可隐藏）；
              此处只管理用户菜单栏的各项 menu_visible */}
          {tab === "display" ? (
            <div className="settings-display">
              <h3 className="settings-sub__title">菜单栏展示 <span className="settings-sub__hint">（参数 1 显示 / 0 隐藏，保存于 config.json，即时生效）</span></h3>

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

          {/* ================= 更新设置（GitHub 检查更新 + 工具箱介绍/点赞 + 版本更新记录） =================
              检查更新：update.check 对比本地版本与内置仓库（UPDATE_REPO）latest Release；无仓库配置 UI */}
          {tab === "update" ? (
            <div className="settings-update">
              <h3 className="settings-sub__title">检查更新 <span className="settings-sub__hint">（检查内置仓库 {UPDATE_REPO} 的最新 Release，与本地版本对比）</span></h3>

              <div className="form-row">
                <button
                  className="form-btn primary"
                  disabled={upChecking}
                  title="检查 GitHub 是否有新版本"
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

              {/* v2.2.4：程序内一键下载安装。仅 Windows 且 Release 含 win-setup.exe 时可用；
                  其它平台提示前往 GitHub 手动下载。 */}
              {upResult.kind === "update" ? (
                <div className="up-install">
                  {upResult.platform.includes("win") && upResult.asset ? (
                    <>
                      <div className="form-row">
                        {!upPath ? (
                          <button
                            className="form-btn primary"
                            disabled={upDownloading}
                            title="从 GitHub 下载安装包到应用 updates/ 目录"
                            onClick={() => void startDownload()}
                          >
                            {upDownloading ? <RefreshCw size={13} className="spin" /> : <Download size={13} />}
                            {upDownloading ? `下载中 ${upPercent}%` : "下载并安装"}
                          </button>
                        ) : (
                          <button
                            className="form-btn primary"
                            disabled={upInstalling}
                            title="启动静默安装，应用将自动退出以完成更新"
                            onClick={() => void startInstall()}
                          >
                            {upInstalling ? <RefreshCw size={13} className="spin" /> : <Download size={13} />}
                            {upInstalling ? "正在安装…" : "立即安装"}
                          </button>
                        )}
                        <span className="settings-sub__hint">
                          {upPath ? `已下载：${upResult.asset.name}` : `安装包：${upResult.asset.name}（${(upResult.asset.size / 1048576).toFixed(1)} MB）`}
                        </span>
                      </div>
                      {upDownloading ? (
                        <div className="up-progress">
                          <div className="up-progress__bar" style={{ width: `${upPercent}%` }} />
                        </div>
                      ) : null}
                      <p className="up-install__note">
                        点「立即安装」后将启动静默安装并自动退出应用；安装完成重新打开即为新版本。若安装失败可到上方「查看更新内容」手动下载。
                      </p>
                    </>
                  ) : (
                    <p className="up-install__note">
                      当前平台暂不支持程序内自动安装，请点上方「查看更新内容」前往 GitHub 手动下载。
                    </p>
                  )}
                </div>
              ) : null}

              {/* 工具箱介绍 + GitHub 点赞推荐 */}
              <div className="update-intro">
                <div className="update-intro__badge">破晓 · 工具箱</div>
                <p className="update-intro__text">
                  Daybreak Toolbox 是一款面向 Windows 渗透测试的工具箱：菜单栏/导航栏/工具全可配置，
                  支持全局快捷键一键启动本机工具，本地运行、数据不出机器。
                  若觉得好用，欢迎去 GitHub 点个 Star 支持持续更新！
                </p>
                <div className="update-intro__star">
                  <a
                    className="update-star"
                    href={`https://github.com/${UPDATE_REPO}`}
                    target="_blank"
                    rel="noreferrer"
                    title="在新标签页打开仓库并点赞（Star）"
                  >
                    <Star size={15} /> 去 GitHub 点赞
                  </a>
                </div>
              </div>

              {/* 版本更新记录（历史静态数据） */}
              <AboutDialog />
            </div>
          ) : null}
          </div>
        </div>
        {/* 右下角拉伸把手（min 680x420 / max 1600x1000，且不超过视口；首次拖动锚定左上角 → 单向拉伸；全屏时隐藏） */}
        {!fs ? (
          <div
            className={"resize-grip" + (resizing ? " is-resizing" : "")}
            onPointerDown={onGripPointerDown}
            title="拖动拉伸（最小 680x420）"
          />
        ) : null}
      </div>
    </div>
  );
}
