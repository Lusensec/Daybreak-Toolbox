/** 顶栏系统固定菜单栏（AppShell NAV 的 label，与菜单渲染顺序一致）。
 *  显隐参数存 config.json 保留键 __fixed_menu_visible__（1 显示 / 0 隐藏）。
 *  SettingsModal「菜单栏展示」与 AppShell 顶栏共用此常量，避免两处标签漂移。
 *  v2.1.3：AI 对话 / 终端管理 / 编解码 / 汉英翻译 / 临时笔记 五个固定功能面板已移除，
 *  固定菜单只剩「首页」（工具箱主界面）；其余入口全部来自用户自定义菜单（config.json）。 */
export const FIXED_MENUS = ["首页"];
