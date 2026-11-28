/**
 * 快捷键：槽位(slot) 体系 + 组合键(combo) 工具。
 *
 * 槽位键（与 bridge/shortcut_service.py 对齐）：
 *   panel            回到面板（首页）
 *   dyn:<菜单名>     第 N 个用户动态菜单栏
 *   fix:<菜单名>     第 N 个系统固定菜单栏
 *   nav:<n>          当前菜单栏下第 n 个导航项（n=1..9，1=首页）
 *   tool:<菜单>__<工具>  工具快捷键
 *
 * 组合串规范化：[Ctrl+][Alt+][Shift+]<Key>（修饰键固定序 Ctrl<Alt<Shift；
 * 可全省略 → 单键也算组合，如 "K" / "F5"；Key ∈ A-Z / 0-9 / F1-F12 / Space）。
 * Ctrl 非必须；须含至少一个普通键（纯修饰键不算）。
 */
import { FIXED_MENUS } from "../menu/fixedMenus";

export const SLOT_PANEL = "panel";
export const slotDyn = (menu: string) => `dyn:${menu}`;
export const slotFix = (menu: string) => `fix:${menu}`;
export const slotNav = (n: number) => `nav:${n}`;
export const slotTool = (menu: string, tool: string) => `tool:${menu}__${tool}`;

/** 固定菜单栏参与快捷键的菜单：「首页」不配快捷键（「回到面板」槽位即可到达，无需独占组合键）。
 *  v2.1.3：五个固定功能面板已移除，固定菜单只剩「首页」→ 本列表为空，fix: 槽位不再产生默认组合。 */
export const SHORTCUT_FIX_MENUS = FIXED_MENUS.filter((n) => n !== "首页");

/** 工具槽（tool:<菜单>__<工具>）默认组合：按工具列表顺序（从左到右、从上到下）Ctrl+Alt+1、2、3… */
export const defaultToolCombo = (i: number) => `Ctrl+Alt+${i}`;

/** 工具列表 → 槽位默认组合表（1-based；列表顺序即编号顺序） */
export function toolDefaults(list: { menu: string; name: string }[]): Record<string, string> {
  const out: Record<string, string> = {};
  list.forEach((t, i) => { out[slotTool(t.menu, t.name)] = defaultToolCombo(i + 1); });
  return out;
}

/** 默认组合（前端按当前菜单顺序生成，不落盘；工具槽无默认）。
 *  固定菜单默认按 SHORTCUT_FIX_MENUS 编号（_fixMenus 参数仅为调用兼容保留，不再使用）。 */
export function defaultCombo(slotKey: string, dynMenus: string[], _fixMenus: string[]): string | undefined {
  if (slotKey === SLOT_PANEL) return "Ctrl+Space";
  if (slotKey.startsWith("dyn:")) {
    const i = dynMenus.indexOf(slotKey.slice(4));
    return i >= 0 ? `Ctrl+${i + 1}` : undefined;
  }
  if (slotKey.startsWith("fix:")) {
    const i = SHORTCUT_FIX_MENUS.indexOf(slotKey.slice(4)); // 「首页」槽位不再分配默认
    return i >= 0 ? `Ctrl+Alt+${i + 1}` : undefined;
  }
  if (slotKey.startsWith("nav:")) {
    const n = Number(slotKey.slice(4));
    return n >= 1 && n <= 9 ? `Ctrl+Shift+${n}` : undefined;
  }
  return undefined; // tool 槽位默认组合不在静态表里：由 toolDefaults(工具列表) 按顺序生成
}

/** 生效组合：已存值优先（""=显式停用），否则默认（工具槽默认需显式传 toolDefaults），再否则无 */
export function effectiveCombo(
  map: Record<string, string>,
  slotKey: string,
  dynMenus: string[],
  _fixMenus: string[],
  toolDefaultsMap?: Record<string, string>,
): string {
  if (Object.prototype.hasOwnProperty.call(map, slotKey)) return map[slotKey] ?? "";
  const d = defaultCombo(slotKey, dynMenus, _fixMenus);
  if (d) return d;
  return toolDefaultsMap?.[slotKey] ?? ""; // 工具槽：默认按列表顺序生成
}

/** 当前生效的全部槽位（面板 + 动态菜单 + 固定菜单[不含首页] + 导航 1..9 + 工具槽）。
 *  tools 传入时用「全部工具槽 + 默认组合」参与匹配；缺省仅已存工具槽（兼容旧调用）。 */
export function allSlots(
  map: Record<string, string>,
  dynMenus: string[],
  _fixMenus: string[],
  tools?: { menu: string; name: string }[],
): string[] {
  const toolSlots = tools
    ? tools.map((t) => slotTool(t.menu, t.name))
    : Object.keys(map).filter((k) => k.startsWith("tool:"));
  return [
    SLOT_PANEL,
    ...dynMenus.map(slotDyn),
    ...SHORTCUT_FIX_MENUS.map(slotFix), // 旧表里的 fix:首页 条目不再参与匹配/冲突检测（惰性残留，无害）
    ...Array.from({ length: 9 }, (_, i) => slotNav(i + 1)),
    ...toolSlots,
  ];
}

/** 键盘事件 → 组合串（不满足条件返回 null：无普通键 / 不支持的键）。
 *  任意键或组合均可（Ctrl 非必须，如单键 "K" / "F5"；修饰键顺序固定 Ctrl<Alt<Shift）。
 *  键位用 e.code 归一化（Shift+数字 时 e.key 会变成 !@#…，e.code 才是稳定语义）。 */
export function eventCombo(e: KeyboardEvent): string | null {
  const mods: string[] = [];
  if (e.ctrlKey) mods.push("Ctrl");
  if (e.altKey) mods.push("Alt");
  if (e.shiftKey) mods.push("Shift");
  let key = "";
  if (e.code.startsWith("Digit")) key = e.code.slice(5);        // Digit1 → "1"（前缀 5 字符）
  else if (e.code.startsWith("Key")) key = e.code.slice(3);     // KeyZ → "Z"（前缀 3 字符）
  else if (e.code === "Space") key = "Space";
  else if (/^F\d{1,2}$/.test(e.code)) key = e.code;             // F1-F12
  else return null;                                             // 其余键（修饰键/符号/方向键…）不支持
  return [...mods, key].join("+");
}

/** 冲突检测：两个以上槽位生效同一组合 → 返回冲突槽位集合（tools 传入时工具默认组合也参与） */
export function findConflicts(
  map: Record<string, string>,
  dynMenus: string[],
  _fixMenus: string[],
  tools?: { menu: string; name: string }[],
): Set<string> {
  const tDefaults = tools?.length ? toolDefaults(tools) : undefined;
  const byCombo = new Map<string, string[]>();
  for (const s of allSlots(map, dynMenus, _fixMenus, tools)) {
    const c = effectiveCombo(map, s, dynMenus, _fixMenus, tDefaults);
    if (!c) continue;
    byCombo.set(c, [...(byCombo.get(c) ?? []), s]);
  }
  const out = new Set<string>();
  for (const group of byCombo.values()) if (group.length > 1) group.forEach((s) => out.add(s));
  return out;
}
