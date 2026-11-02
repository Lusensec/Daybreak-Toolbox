"""tests/test_ai_config.py：ai_config service 测试（临时目录隔离，不碰真实 config/）。

覆盖：
  - 文件缺失时按 5 模型默认模板创建（含 AI_kind 补齐）
  - 旧双文件（ai_ask.json + ai_history.json）自动合并迁移到 ai.json
  - get_ai_config 返回 models(按别名排序) + kinds + config
  - 旧文件字段补齐（别名 / base url / 模型ID / AI_kind）
  - set_ai_config：别名必填（AI_ALIAS_REQUIRED）、单栏/分栏、其余模型清零、原子写
  - add_ai_model / remove_ai_model：新增（内部名唯一、别名必填、kind 校验）、
    删除（启用中禁删、不存在报错）
  - 非法 page_nums 回落 1、损坏文件 INTERNAL
  - 历史轮数（与模型配置合存 ai.json 的 history 字段）钳制 10..100
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bridge import ai_config


@pytest.fixture
def root(tmp_path, monkeypatch):
    ai_config.set_root(tmp_path)
    yield tmp_path
    ai_config.set_root(Path(__file__).resolve().parent.parent / "bridge" / "..")


def _mk(root: Path, models: dict, history_rounds: int | None = None) -> None:
    """模拟旧双文件布局（迁移测试用）。"""
    d = root / "config"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ai_ask.json").write_text(json.dumps(models, ensure_ascii=False), encoding="utf-8")
    if history_rounds is not None:
        (d / "ai_history.json").write_text(json.dumps({"rounds": history_rounds}), encoding="utf-8")


def test_missing_file_creates_default_template(root):
    assert not (root / "config" / "ai.json").exists()
    r = ai_config.get_ai_config()
    assert set(r["models"]) == {"kimi_ai", "通义千问", "智谱清言", "deepseek_api", "ollama"}
    assert set(r["kinds"]) == {"openai", "zhipu", "ollama"}
    m = r["config"]["kimi_ai"]
    assert m["AI_API"] == "" and m["ai_color"] == "" and m["use_page"] == 0
    assert m["AI_alias"] == "" and m["AI_base_url"] == "" and m["AI_model_id"] == ""
    assert m["AI_kind"] == "openai"
    assert (root / "config" / "ai.json").exists()
    # 单文件结构：models + history
    raw = json.loads((root / "config" / "ai.json").read_text(encoding="utf-8"))
    assert "models" in raw and raw["history"]["rounds"] == ai_config.HISTORY_DEFAULT


def test_legacy_files_migrated_to_single_ai_json(root):
    _mk(root, {"kimi_ai": {"AI_API": "sk-x", "ai_color": "", "use_page": 1}}, history_rounds=50)
    r = ai_config.get_ai_config()
    assert r["config"]["kimi_ai"]["AI_API"] == "sk-x"
    assert ai_config.history_rounds() == 50
    raw = json.loads((root / "config" / "ai.json").read_text(encoding="utf-8"))
    assert raw["models"]["kimi_ai"]["AI_API"] == "sk-x"
    assert raw["history"]["rounds"] == 50
    # 迁移只读旧文件，不删除（删除由用户/清理流程负责）
    assert (root / "config" / "ai_ask.json").exists()


def test_legacy_file_gets_new_fields_backfilled(root):
    _mk(root, {"kimi_ai": {"AI_API": "sk-x", "ai_color": "", "use_page": 1}})
    r = ai_config.get_ai_config()
    m = r["config"]["kimi_ai"]
    # 旧字段保留 + 新字段补齐（kimi 的 legacy kind = openai）
    assert m["AI_API"] == "sk-x" and m["use_page"] == 1
    assert m["AI_alias"] == "" and m["AI_base_url"] == "" and m["AI_model_id"] == ""
    assert m["AI_kind"] == "openai"


def test_get_after_set_roundtrip(root):
    ai_config.get_ai_config()  # 建模板
    r = ai_config.set_ai_config("kimi_ai", "sk-123", 1, alias="我的Kimi",
                                base_url="https://api.moonshot.cn/v1",
                                model_id="moonshot-v1-128k")
    assert r["ok"] and r["model"] == "kimi_ai" and r["model_two"] is None
    cfg = ai_config.get_ai_config()["config"]
    assert cfg["kimi_ai"]["AI_API"] == "sk-123"
    assert cfg["kimi_ai"]["use_page"] == 1
    assert cfg["kimi_ai"]["AI_alias"] == "我的Kimi"
    assert cfg["kimi_ai"]["AI_base_url"] == "https://api.moonshot.cn/v1"
    assert cfg["kimi_ai"]["AI_model_id"] == "moonshot-v1-128k"
    for name in ("通义千问", "智谱清言", "deepseek_api", "ollama"):
        assert cfg[name]["use_page"] == 0
    raw = json.loads((root / "config" / "ai.json").read_text(encoding="utf-8"))
    assert raw["models"]["kimi_ai"]["AI_API"] == "sk-123"
    assert raw["models"]["kimi_ai"]["AI_alias"] == "我的Kimi"
    # 改 models 不动 history
    assert raw["history"]["rounds"] == ai_config.HISTORY_DEFAULT


def test_set_requires_alias(root):
    ai_config.get_ai_config()
    with pytest.raises(ai_config.AiConfigError) as exc:
        ai_config.set_ai_config("kimi_ai", "sk-1", 1)  # 无 alias
    assert exc.value.code == "AI_ALIAS_REQUIRED"


def test_set_split_page_writes_model_two(root):
    ai_config.get_ai_config()
    r = ai_config.set_ai_config("kimi_ai", "sk-1", 2, "ollama", alias="K")
    cfg = ai_config.get_ai_config()["config"]
    assert cfg["kimi_ai"]["use_page"] == 2
    assert cfg["ollama"]["use_page"] == 2
    assert r["model_two"] == "ollama"


def test_set_ai_page_layout(root):
    ai_config.get_ai_config()
    # 单栏：pane1=kimi
    r = ai_config.set_ai_page(1, "kimi_ai")
    cfg = ai_config.get_ai_config()["config"]
    assert cfg["kimi_ai"]["use_page"] == 1
    for n in ("通义千问", "智谱清言", "deepseek_api", "ollama"):
        assert cfg[n]["use_page"] == 0
    # 双栏：pane1=kimi, pane2=ollama
    r = ai_config.set_ai_page(2, "kimi_ai", "ollama")
    cfg = ai_config.get_ai_config()["config"]
    assert cfg["kimi_ai"]["use_page"] == 2 and cfg["ollama"]["use_page"] == 2
    # 只改布局不校验别名/API：即便 kimi 未填别名也可保存
    assert r["model_two"] == "ollama"
    # 双栏但 model_two 与主栏相同 → 拒绝
    with pytest.raises(ai_config.AiConfigError) as exc:
        ai_config.set_ai_page(2, "kimi_ai", "kimi_ai")
    assert exc.value.code == "AI_MODEL_TWO_NOT_FOUND"


def test_set_split_page_requires_distinct_valid_model_two(root):
    ai_config.get_ai_config()
    for bad in (None, "", "kimi_ai", "no_such_model"):
        with pytest.raises(ai_config.AiConfigError) as exc:
            ai_config.set_ai_config("kimi_ai", "sk-1", 2, bad, alias="K")
        assert exc.value.code == "AI_MODEL_TWO_NOT_FOUND"


def test_unknown_model_raises(root):
    ai_config.get_ai_config()
    with pytest.raises(ai_config.AiConfigError) as exc:
        ai_config.set_ai_config("foo", "sk", 1, alias="X")
    assert exc.value.code == "AI_MODEL_NOT_FOUND"


def test_page_nums_clamped_to_valid(root):
    ai_config.get_ai_config()
    r = ai_config.set_ai_config("ollama", "http://127.0.0.1:11434/", 7, alias="O")
    assert r["use_page"] == 1
    assert ai_config.get_ai_config()["config"]["ollama"]["AI_API"] == "http://127.0.0.1:11434/"


def test_add_remove_model(root):
    ai_config.get_ai_config()
    # 新增（别名必填 + kind 校验 + 内部名唯一）
    with pytest.raises(ai_config.AiConfigError) as exc:
        ai_config.add_ai_model("my_model", alias="", kind="openai")
    assert exc.value.code == "AI_ALIAS_REQUIRED"
    with pytest.raises(ai_config.AiConfigError) as exc:
        ai_config.add_ai_model("my_model", alias="M", kind="nope")
    assert exc.value.code == "AI_KIND_INVALID"
    r = ai_config.add_ai_model("my_model", alias="M", kind="openai")
    assert r["ok"] and "my_model" in ai_config.get_ai_config()["models"]
    with pytest.raises(ai_config.AiConfigError) as exc:
        ai_config.add_ai_model("kimi_ai", alias="K2")  # 已存在
    assert exc.value.code == "AI_MODEL_EXISTS"
    # 删除：启用中的模型禁删
    ai_config.set_ai_config("my_model", "sk", 1, alias="M")  # use_page=1
    with pytest.raises(ai_config.AiConfigError) as exc:
        ai_config.remove_ai_model("my_model")
    assert exc.value.code == "AI_MODEL_IN_USE"
    ai_config.set_ai_config("kimi_ai", "sk", 1, alias="K")  # my_model 被清零
    r = ai_config.remove_ai_model("my_model")
    assert r["ok"] and "my_model" not in ai_config.get_ai_config()["models"]
    with pytest.raises(ai_config.AiConfigError) as exc:
        ai_config.remove_ai_model("no_such")
    assert exc.value.code == "AI_MODEL_NOT_FOUND"


def test_models_sorted_by_alias(root):
    ai_config.get_ai_config()
    ai_config.set_ai_config("ollama", "http://127.0.0.1:11434", 1, alias="aaa最前")
    ai_config.set_ai_config("kimi_ai", "sk", 1, alias="zzz最后")
    models = ai_config.get_ai_config()["models"]
    # 别名非空的按别名序在前；kimi(zzz) 排 ollama(aaa) 之后
    assert models.index("ollama") < models.index("kimi_ai")
    assert models[0] == "ollama"


def test_corrupt_file_raises_internal(root):
    d = root / "config"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ai.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ai_config.AiConfigError) as exc:
        ai_config.get_ai_config()
    assert exc.value.code == "INTERNAL"


def test_history_default_when_missing(root):
    # 未写过 ai.json → history 返回默认 20
    assert ai_config.get_ai_history()["rounds"] == ai_config.HISTORY_DEFAULT
    assert ai_config.get_ai_history()["min"] == 10
    assert ai_config.get_ai_history()["max"] == 100


def test_history_set_and_clamp(root):
    r = ai_config.set_ai_history(50)
    assert r["ok"] and r["rounds"] == 50
    assert ai_config.history_rounds() == 50
    # 越界钳制：5 → 10；500 → 100
    assert ai_config.set_ai_history(5)["rounds"] == 10
    assert ai_config.history_rounds() == 10
    assert ai_config.set_ai_history(500)["rounds"] == 100
    assert ai_config.history_rounds() == 100
    # 非数字回落默认
    assert ai_config.set_ai_history("abc")["rounds"] == 20
    # 文件确实落盘（ai.json 的 history 段）
    raw = json.loads((root / "config" / "ai.json").read_text(encoding="utf-8"))
    assert raw["history"]["rounds"] == 20


def test_history_migrated_from_legacy_file(root):
    _mk(root, {"kimi_ai": {"AI_API": "sk"}}, history_rounds=37)
    assert ai_config.get_ai_history()["rounds"] == 37
