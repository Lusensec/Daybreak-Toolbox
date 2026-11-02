/**
 * AI provider 常量 —— 与 bridge/ai_service.PROVIDERS 严格对齐。
 * value 即 bridge 侧 Chat_AI.ai_main 的 ai_name；label 为展示名。
 */
export const PROVIDERS = [
  "kimi_ai",
  "通义千问",
  "智谱清言",
  "deepseek_api",
  "ollama",
] as const;

export const PROVIDER_LABELS: Record<string, string> = {
  kimi_ai: "Kimi（Moonshot）",
  通义千问: "通义千问（Qwen）",
  智谱清言: "智谱清言（GLM-4）",
  deepseek_api: "DeepSeek",
  ollama: "Ollama（本地）",
};

/** 动态模型条目（来自 ai.get_config，含自定义模型；别名优先展示） */
export interface AiProviderInfo {
  name: string;
  label: string;
  active: boolean; // use_page != 0
}
