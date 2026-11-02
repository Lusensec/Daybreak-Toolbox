"""AI 配置 service：config/ai.json 的 CRUD（模型配置 + 历史轮数 合存单文件）。

设计（对齐旧版 fun.py 七、AI对话模型设置，并合并 ai_ask.json 与 ai_history.json）：
  - 单文件 config/ai.json：
        { "models": { <名称>: {AI_API, AI_alias, AI_base_url, AI_model_id, AI_kind, ai_color, use_page} },
          "history": { "rounds": N } }
  - 不复用旧 fun.py 的全局缓存（其顶部 from tkinter import *，headless 不干净）；
    每次读盘 + 原子写，语义 1:1 复刻：
      - get_ai_json_all / get_ai_json_name_all：读全量 + 名称列表
      - create_ai_json：文件缺失时按 5 模型默认模板创建
      - update_ai_json：page_nums==2 时给 model_two 写 use_page=2；
          给 model 写 AI_API + use_page；其余模型 use_page 全部清零
  - 迁移（一次性）：ai.json 缺失时，若存在旧 config/ai_ask.json / ai_history.json 则合并并入，
    否则用默认模板；落盘后旧文件可安全删除。
  - 原子写：临时文件 + os.replace，防截断。

错误码：AI_MODEL_NOT_FOUND / AI_MODEL_TWO_NOT_FOUND / INTERNAL
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

# 项目根（bridge/ai_config.py → 上一级）
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
# 合并后的单文件（models + history）
_CONFIG_FILE = _PROJECT_ROOT / "config" / "ai.json"
# 旧双文件（仅迁移来源，迁移完成后删除）
_LEGACY_ASK_FILE = _PROJECT_ROOT / "config" / "ai_ask.json"
_LEGACY_HISTORY_FILE = _PROJECT_ROOT / "config" / "ai_history.json"

HISTORY_MIN, HISTORY_MAX, HISTORY_DEFAULT = 10, 100, 20

# fun.create_ai_json 的默认模板（1:1 + 扩展字段：别名 / base url / 模型ID / 类型）
def _tpl(kind: str) -> dict:
    return {"AI_API": "", "AI_alias": "", "AI_base_url": "", "AI_model_id": "",
            "AI_kind": kind, "ai_color": "", "use_page": 0}

DEFAULT_TEMPLATE = {
    "kimi_ai":      _tpl("openai"),
    "通义千问":      _tpl("openai"),
    "智谱清言":      _tpl("zhipu"),
    "deepseek_api": _tpl("openai"),
    "ollama":       _tpl("ollama"),
}

# 合法 provider 类型（决定 test_ai 走哪条调用链）
VALID_KINDS = ("openai", "zhipu", "ollama")


def set_root(root) -> None:
    """覆写项目根（测试用临时目录，避免污染真实 config/ai.json）。"""
    global _PROJECT_ROOT, _CONFIG_FILE, _LEGACY_ASK_FILE, _LEGACY_HISTORY_FILE
    _PROJECT_ROOT = Path(root)
    _CONFIG_FILE = _PROJECT_ROOT / "config" / "ai.json"
    _LEGACY_ASK_FILE = _PROJECT_ROOT / "config" / "ai_ask.json"
    _LEGACY_HISTORY_FILE = _PROJECT_ROOT / "config" / "ai_history.json"


class AiConfigError(Exception):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


# ---- 合法 provider 默认（chat_once / test_ai 的 base_url / model 回退）----
_PROVIDER_DEFAULTS = {
    "kimi_ai":      {"kind": "openai", "base_url": "https://api.moonshot.cn/v1",
                     "model": "moonshot-v1-128k"},
    "通义千问":      {"kind": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                      "model": "qwen-turbo"},
    "智谱清言":      {"kind": "zhipu",  "base_url": "", "model": "glm-4-air"},
    "deepseek_api": {"kind": "openai", "base_url": "https://api.deepseek.com",
                     "model": "deepseek-chat"},
    "ollama":       {"kind": "ollama", "base_url": "", "model": ""},
}


def _migrate_legacy_models() -> dict:
    """旧 ai_ask.json → models dict；无则默认模板。"""
    if _LEGACY_ASK_FILE.exists():
        try:
            data = json.loads(_LEGACY_ASK_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data:
                return data
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_TEMPLATE))


def _migrate_legacy_history_rounds() -> int:
    """旧 ai_history.json → rounds；无则默认。"""
    if _LEGACY_HISTORY_FILE.exists():
        try:
            v = int(json.loads(_LEGACY_HISTORY_FILE.read_text(encoding="utf-8")).get("rounds", HISTORY_DEFAULT))
            return max(HISTORY_MIN, min(HISTORY_MAX, v))
        except Exception:
            pass
    return HISTORY_DEFAULT


def _backfill_models(models: dict) -> None:
    """旧模型字段补齐：保证每个模型都有 别名 / base url / 模型ID / 类型 / API / 颜色 / use_page。"""
    legacy_kind = {k: v["kind"] for k, v in _PROVIDER_DEFAULTS.items()}
    for _name, model in models.items():
        if not isinstance(model, dict):
            model = {}
        for key in ("AI_alias", "AI_base_url", "AI_model_id"):
            model.setdefault(key, "")
        model.setdefault("AI_kind", legacy_kind.get(_name, "openai"))
        model.setdefault("AI_API", "")
        model.setdefault("ai_color", "")
        model.setdefault("use_page", 0)


def _load_full() -> dict:
    """完整 wrapper {models, history}。文件缺失 → 合并旧双文件或默认模板并落盘；损坏 → INTERNAL。"""
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise AiConfigError("INTERNAL", "config/ai.json 已损坏，请删除后重新配置")
        if not isinstance(data, dict):
            data = {}
    else:
        data = {"models": _migrate_legacy_models(),
                "history": {"rounds": _migrate_legacy_history_rounds()}}
        _atomic_write(_CONFIG_FILE, data)

    if not isinstance(data.get("models"), dict):
        data["models"] = json.loads(json.dumps(DEFAULT_TEMPLATE))
    if not isinstance(data.get("history"), dict):
        data["history"] = {"rounds": HISTORY_DEFAULT}
    _backfill_models(data["models"])
    return data


def _load() -> dict:
    return _load_full()["models"]


def _sorted_models(cfg: dict) -> list:
    """按 别名（空则内部名）排序，供下拉展示。"""
    return sorted(cfg.keys(),
                  key=lambda k: ((cfg[k].get("AI_alias") or "").strip() or k, k))


def _atomic_write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".ai_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=4)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _save_models(cfg: dict) -> None:
    """写回 models（保留当前 history）。"""
    data = _load_full()
    data["models"] = cfg
    _atomic_write(_CONFIG_FILE, data)


def get_ai_config() -> dict:
    """全量返回：{ models: [名称...（按别名排序）], kinds: [合法类型],
    config: {名称: {...}} }。"""
    cfg = _load()
    return {"models": _sorted_models(cfg), "kinds": list(VALID_KINDS), "config": cfg}


# ---- 历史轮数（对话上下文保留多少轮）：与模型配置合存 ai.json 的 history 字段 ----
def history_rounds() -> int:
    """当前配置的历史轮数（10..100，缺省 20）。每次读取，供 ai_service 动态裁剪。"""
    try:
        data = _load_full()
        v = int(data.get("history", {}).get("rounds", HISTORY_DEFAULT))
        return max(HISTORY_MIN, min(HISTORY_MAX, v))
    except Exception:
        return HISTORY_DEFAULT


def get_ai_history() -> dict:
    """返回 {rounds, min, max, default}。"""
    return {"rounds": history_rounds(), "min": HISTORY_MIN, "max": HISTORY_MAX,
            "default": HISTORY_DEFAULT}


def set_ai_history(rounds: int) -> dict:
    """写入历史轮数（钳制到 10..100）。即时生效：ai_service 每次请求读盘。"""
    rounds = int(rounds) if str(rounds).isdigit() else HISTORY_DEFAULT
    rounds = max(HISTORY_MIN, min(HISTORY_MAX, rounds))
    data = _load_full()
    data["history"] = {"rounds": rounds}
    _atomic_write(_CONFIG_FILE, data)
    return {"ok": True, "rounds": rounds}


def set_ai_page(page_nums: int, model_one: str, model_two: str = "") -> dict:
    """保存「分栏数量」：只调整 use_page 布局（pane1=model_one，pane2=model_two），
    不改任何模型的 API/别名等字段；其余模型清零。即时生效（广播 ai.config_changed → 前端重载分栏）。
    校验：page==2 时 model_two 必须存在且 != model_one。"""
    cfg = _load()
    page_nums = int(page_nums) if str(page_nums).isdigit() else 1
    if page_nums not in (1, 2):
        page_nums = 1
    model_one = (model_one or "").strip()
    model_two = (model_two or "").strip()
    if model_one not in cfg:
        raise AiConfigError("AI_MODEL_NOT_FOUND", f"主分栏模型 {model_one} 不存在")
    if page_nums == 2:
        if model_two not in cfg or model_two == model_one:
            raise AiConfigError("AI_MODEL_TWO_NOT_FOUND", "分栏数量为 2 时请选择有效的第二个分栏模型")
        cfg[model_two]["use_page"] = 2
    keep = {model_one, model_two} if page_nums == 2 else {model_one}
    for name in cfg:
        if name not in keep:
            cfg[name]["use_page"] = 0
    cfg[model_one]["use_page"] = page_nums
    _save_models(cfg)
    return {"ok": True, "page_nums": page_nums, "model_one": model_one,
            "model_two": model_two or None, "models": _sorted_models(cfg)}


def add_ai_model(model: str, alias: str = "", kind: str = "openai") -> dict:
    """新增自定义模型（别名必填）。内部名不能与已有重名。"""
    cfg = _load()
    model = (model or "").strip()
    if not model:
        raise AiConfigError("AI_MODEL_EMPTY", "模型内部名称不能为空")
    if model in cfg:
        raise AiConfigError("AI_MODEL_EXISTS", f"模型 {model} 已存在")
    alias = (alias or "").strip()
    if not alias:
        raise AiConfigError("AI_ALIAS_REQUIRED", "别名是必填项，请填写别名")
    if kind not in VALID_KINDS:
        raise AiConfigError("AI_KIND_INVALID", f"未知类型 {kind}（合法：{'/'.join(VALID_KINDS)}）")
    cfg[model] = _tpl(kind)
    cfg[model]["AI_alias"] = alias
    _save_models(cfg)
    return {"ok": True, "model": model, "alias": alias, "models": _sorted_models(cfg)}


def remove_ai_model(model: str) -> dict:
    """删除模型（内部名）。当前启用（use_page!=0）的模型禁止删除。"""
    cfg = _load()
    model = (model or "").strip()
    if model not in cfg:
        raise AiConfigError("AI_MODEL_NOT_FOUND", f"模型 {model} 不存在")
    if cfg[model].get("use_page") not in (0, None, ""):
        raise AiConfigError("AI_MODEL_IN_USE",
                            f"模型 {model} 正在启用（use_page={cfg[model]['use_page']}），请先停用再删除")
    del cfg[model]
    _save_models(cfg)
    return {"ok": True, "removed": model, "models": _sorted_models(cfg)}


def set_ai_config(model: str, api: str, page_nums: int,
                  model_two: Optional[str] = None,
                  alias: str = "", base_url: str = "", model_id: str = "",
                  kind: str = "") -> dict:
    """复刻旧版 update_ai_json 的写入语义（含 校验）。
    扩展字段：别名（必填）/ base url / 模型ID / 类型 一并落盘到该模型配置。"""
    cfg = _load()
    model = (model or "").strip()
    if model not in cfg:
        raise AiConfigError("AI_MODEL_NOT_FOUND", f"AI 模型 {model} 不存在")
    alias = (alias or "").strip()
    if not alias:
        raise AiConfigError("AI_ALIAS_REQUIRED", "别名是必填项，请填写别名")
    page_nums = int(page_nums) if str(page_nums).isdigit() else 1
    if page_nums not in (1, 2):
        page_nums = 1

    model_two = (model_two or "").strip()
    if page_nums == 2:
        if model_two == "" or model_two not in cfg or model_two == model:
            raise AiConfigError("AI_MODEL_TWO_NOT_FOUND",
                                "分栏数量为 2 时请选择有效的第二个分栏模型")
        cfg[model_two]["use_page"] = 2

    m = cfg[model]
    m["AI_alias"] = alias
    m["AI_base_url"] = (base_url or "").strip()
    m["AI_model_id"] = (model_id or "").strip()
    if kind:
        if kind not in VALID_KINDS:
            raise AiConfigError("AI_KIND_INVALID", f"未知类型 {kind}（合法：{'/'.join(VALID_KINDS)}）")
        m["AI_kind"] = kind
    m["AI_API"] = (api or "").strip()
    m["use_page"] = page_nums

    for name in cfg:
        if name != model and name != model_two:
            cfg[name]["use_page"] = 0

    _save_models(cfg)
    return {"ok": True, "model": model, "use_page": page_nums,
            "model_two": model_two or None, "models": _sorted_models(cfg)}


# ---- 连接测试 / 实时对话：均走 chat_once（配置驱动，每次读盘，无需重启） ----
def chat_once(message: str, model: str, history: Optional[list] = None,
              temperature: float = 0.3, timeout: int = 60) -> dict:
    """基于**最新磁盘配置**（每次 _load，无模块缓存 → 无需重启）执行一次对话补全。

    返回 {ok, text, label, kind}。history: [{"role","content"}…] 由调用方管理。
    三种类型（与 ai.test 同一套链路）：
      openai：AI_API=Key，AI_base_url（回退 provider 默认 / OpenAI 官方），AI_model_id
      zhipu ：AI_API=Key，zhipuai SDK
      ollama：AI_API（服务地址，回退 AI_base_url），AI_model_id（空则 /api/tags 取第一个）
    """
    cfg = _load()
    entry = cfg.get(model)
    if entry is None:
        return {"ok": False, "text": f"AI 模型 {model} 不存在，请在「AI模型设置」中添加",
                "kind": "", "label": model}
    d = _PROVIDER_DEFAULTS.get(model, {})
    kind = (entry.get("AI_kind") or d.get("kind") or "openai").strip().lower()
    api = (entry.get("AI_API") or "").strip()
    base_url = (entry.get("AI_base_url") or "").strip()
    model_id = (entry.get("AI_model_id") or "").strip()
    label = (entry.get("AI_alias") or "").strip() or model
    msgs: list = (history or []) + [{"role": "user", "content": message}]

    if kind == "openai":
        if not api:
            return {"ok": False, "text": f"[{label}] 未填写 API Key，请在「AI模型设置」配置后再试",
                    "kind": kind, "label": label}
        if not model_id:
            model_id = d.get("model", "")
        if not model_id:
            return {"ok": False, "text": f"[{label}] 未填写模型ID（OpenAI 兼容协议需要，如 gpt-4o / deepseek-chat）",
                    "kind": kind, "label": label}
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api,
                            base_url=base_url or d.get("base_url") or "https://api.openai.com/v1")
            # 本地 LLM 路由（如 FreeLLMAPI）上游限流/卡流时最长 ~90s 才截断，
            # 客户端超时须 ≥ 该值才能拿到路由器的可读错误而非本地 60s 超时。
            eff_timeout = max(timeout, 120)
            resp = client.chat.completions.create(model=model_id, messages=msgs,
                                                   temperature=temperature, timeout=eff_timeout)
            text = (resp.choices[0].message.content or "").strip()
            return {"ok": True, "text": text, "kind": kind, "label": label}
        except Exception as e:
            msg = str(e)
            hint = ""
            low = msg.lower()
            if "stream interrupted" in low or "mid-stream" in low or "stalled" in low:
                hint = "（上游流被路由器截断：通常是该上游限流/配额不足或卡流，稍后重试或在路由中换 Key/模型）"
            elif "rate limit" in low or "quota" in low or "429" in msg:
                hint = "（上游限流或配额不足，稍后重试）"
            return {"ok": False, "text": f"[{label}] 调用失败：{e}{hint}", "kind": kind, "label": label}

    if kind == "zhipu":
        if not api:
            return {"ok": False, "text": f"[{label}] 未填写 API Key，请在「AI模型设置」配置后再试",
                    "kind": kind, "label": label}
        try:
            from zhipuai import ZhipuAI
            client = ZhipuAI(api_key=api)
            resp = client.chat.completions.create(
                model=model_id or d.get("model") or "glm-4-air",
                messages=msgs, stream=False, timeout=timeout)
            text = (resp.choices[0].message.content or "").strip()
            return {"ok": True, "text": text, "kind": kind, "label": label}
        except Exception as e:
            return {"ok": False, "text": f"[{label}] 调用失败：{e}", "kind": kind, "label": label}

    # ollama：API 字段 = 服务地址
    url = (api or base_url or "http://127.0.0.1:11434").rstrip("/")
    try:
        import requests
        if not model_id:
            tags = requests.get(url + "/api/tags", timeout=15).json().get("models", [])
            if not tags:
                return {"ok": False, "text": f"[{label}] 未找到可用 ollama 模型（{url}）",
                        "kind": kind, "label": label}
            model_id = tags[0]["model"]
        r = requests.post(url + "/api/chat",
                          json={"model": model_id, "messages": msgs, "stream": False},
                          timeout=max(timeout, 60))
        text = (r.json().get("message", {}).get("content") or "").strip()
        return {"ok": True, "text": text, "kind": kind, "label": label}
    except Exception as e:
        return {"ok": False, "text": f"[{label}] 调用失败：{e}", "kind": kind, "label": label}


def test_ai(model: str, api: str, base_url: str = "", model_id: str = "",
            kind: str = "", alias: str = "") -> dict:
    """向指定模型发送 'hello' 做连通性测试，返回 {ok, message}。

    - kind 优先取传入值（动态模型）；未传则回退内置 provider 的硬编码默认。
    - openai/zhipu：base_url / model_id 未填则回退该 provider 的默认。
    - ollama：api 字段视为服务地址，model_id 未填自动取 /api/tags。
    网络/SDK/鉴权 失败统一捕获为 ok=False + 错误信息，不抛异常。
    """
    model = (model or "").strip()
    api = (api or "").strip()
    base_url = (base_url or "").strip()
    model_id = (model_id or "").strip()
    alias = (alias or "").strip()

    d = _PROVIDER_DEFAULTS.get(model, {})
    kind = (kind or d.get("kind") or "openai").strip().lower()
    if kind not in VALID_KINDS:
        return {"ok": False, "message": f"未知模型类型 {kind}（合法：{'/'.join(VALID_KINDS)}）"}
    def_base = d.get("base_url", "")
    def_model = d.get("model", "")
    label = alias or model

    if kind == "openai":
        if not api:
            return {"ok": False, "message": f"[{label}] 未填写 API Key"}
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api, base_url=base_url or def_base or "https://api.openai.com/v1")
            if not model_id and not def_model:
                return {"ok": False, "message": f"[{label}] 未填写模型ID（openai 兼容协议需要）"}
            resp = client.chat.completions.create(
                model=model_id or def_model,
                messages=[{"role": "user", "content": "hello"}],
                temperature=0.3, timeout=120,  # ≥ 路由类服务 90s 流截断阈值
            )
            text = (resp.choices[0].message.content or "").strip()
            return {"ok": True, "message": f"[{label}] 响应正常：{text[:60] or '（空回复）'}"}
        except Exception as e:
            return {"ok": False, "message": f"[{label}] 调用失败：{e}"}

    if kind == "zhipu":
        if not api:
            return {"ok": False, "message": f"[{label}] 未填写 API Key"}
        try:
            from zhipuai import ZhipuAI
            client = ZhipuAI(api_key=api)
            resp = client.chat.completions.create(
                model=model_id or def_model or "glm-4-air",
                messages=[{"role": "user", "content": "hello"}], timeout=30,
            )
            text = (resp.choices[0].message.content or "").strip()
            return {"ok": True, "message": f"[{label}] 响应正常：{text[:60] or '（空回复）'}"}
        except Exception as e:
            return {"ok": False, "message": f"[{label}] 调用失败：{e}"}

    # ollama：api 字段 = 服务地址
    url = (api or base_url or "http://127.0.0.1:11434").rstrip("/")
    try:
        import requests
        if not model_id:
            tags = requests.get(url + "/api/tags", timeout=15).json().get("models", [])
            if not tags:
                return {"ok": False, "message": f"[{label}] 未找到可用 ollama 模型（{url}）"}
            model_id = tags[0]["model"]
        r = requests.post(url + "/api/chat",
                          json={"model": model_id,
                                "messages": [{"role": "user", "content": "hello"}],
                                "stream": False},
                          timeout=60)
        text = (r.json().get("message", {}).get("content") or "").strip()
        return {"ok": True, "message": f"[{label}] 响应正常：{text[:60] or '（空回复）'}"}
    except Exception as e:
        return {"ok": False, "message": f"[{label}] 调用失败：{e}"}
