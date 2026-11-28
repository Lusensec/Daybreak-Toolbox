import { sendCommand } from "../../services/ws";
import { useMenuStore } from "../menu/store";
import { useBrowserStore } from "./store";

/** 启动参数：已知道具元数据时可直接传入，省一次菜单元数据查找 */
export interface LaunchOptions { runType?: string; url?: string }

/** 启动结果：internal 表示已在应用内（内置浏览器）打开 */
export interface LaunchResult { internal: boolean; message: string }

/**
 * 统一工具启动入口。
 *  - 「链接打开」→ 内置浏览器新标签 + 跳转 /browser/:menu/:name
 *  - 其他启动方式 → bridge tool.run（本机执行）
 *  runType / url 未传时从菜单工具元数据补齐。
 */
export async function launchTool(
  menu: string,
  name: string,
  navigate: (path: string) => void,
  opts?: LaunchOptions,
): Promise<LaunchResult> {
  let runType = opts?.runType ?? "";
  let url = opts?.url ?? "";

  if (!runType || !url) {
    const meta = useMenuStore.getState().tools[menu]?.find((t) => t.name === name);
    if (!runType) runType = meta?.runType ?? "";
    if (!url) url = meta?.path ?? "";
  }

  if (runType === "链接打开") {
    if (!url) throw new Error("该链接工具未配置 URL");
    useBrowserStore.getState().openTab(menu, name, url);
    navigate(`/browser/${encodeURIComponent(menu)}/${encodeURIComponent(name)}`);
    return { internal: true, message: `已在内置浏览器打开「${name}」` };
  }

  const r = await sendCommand("tool.run", { menu, name });
  return { internal: false, message: String(r.message ?? "已启动") };
}
