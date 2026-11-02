"""百度翻译（Web 端「汉英翻译」菜单底层；bridge/translate_service.py 惰性 import 本模块）。

凭证来源（优先级）：
  1. 统一密钥文件 config/bridge_secrets.json 的 baidu 字段（工具箱设置「翻译设置」保存处）；
  2. 旧 config/baidu.py（迁移期兜底，正则解析常量，不 import）。
模块级 BAIDU_FANYI_APP_ID / BAIDU_FANYI_SECRET_KEY 在 import 时从磁盘载入，
translate_text 每次调用前执行 refresh_credentials()（由 bridge 在保存凭证后调用；
磁盘无变化时零成本），因此**改凭证无需重启桥接**。测试可直接 monkeypatch 这两个全局。
"""
import hashlib
import json
import random
import re
from pathlib import Path

import requests

_ROOT = Path(__file__).resolve().parent
_SECRETS_FILE = _ROOT / "config" / "bridge_secrets.json"
_LEGACY_PY = _ROOT / "config" / "baidu.py"


def _read_from_disk():
    """返回 (app_id, secret_key)；统一 JSON 优先，旧 baidu.py 兜底；都无 → (None, None)。"""
    try:
        data = json.loads(_SECRETS_FILE.read_text(encoding="utf-8"))
        b = (data or {}).get("baidu") or {}
        app = str(b.get("app_id") or "").strip()
        sec = str(b.get("secret_key") or "").strip()
        if app or sec:
            return app or None, sec or None
    except Exception:
        pass
    try:
        src = _LEGACY_PY.read_text(encoding="utf-8")
        app_m = re.search(r'BAIDU_FANYI_APP_ID\s*=\s*["\']([^"\']*)["\']', src)
        sec_m = re.search(r'BAIDU_FANYI_SECRET_KEY\s*=\s*["\']([^"\']*)["\']', src)
        app = (app_m.group(1).strip() if app_m else "")
        sec = (sec_m.group(1).strip() if sec_m else "")
        if app or sec:
            return app or None, sec or None
    except Exception:
        pass
    return None, None


# import 时载入（测试可 monkeypatch 覆盖；refresh_credentials 负责后续刷新）
BAIDU_FANYI_APP_ID, BAIDU_FANYI_SECRET_KEY = _read_from_disk()


def refresh_credentials() -> None:
    """从磁盘重载凭证到模块全局（bridge 在「翻译设置」保存后调用；无需重启）。"""
    global BAIDU_FANYI_APP_ID, BAIDU_FANYI_SECRET_KEY
    BAIDU_FANYI_APP_ID, BAIDU_FANYI_SECRET_KEY = _read_from_disk()


def translate_text(text, from_lang='zh', to_lang='en'):
    app_id = BAIDU_FANYI_APP_ID
    secret_key = BAIDU_FANYI_SECRET_KEY

    if not app_id or not secret_key:
        return ("未配置百度翻译凭证：请在「工具箱设置 → 翻译设置」中填写 "
                "appid 与密钥后重试（保存至 config/bridge_secrets.json）。")

    url = 'https://fanyi-api.baidu.com/api/trans/vip/translate'

    salt = random.randint(32768, 65536)
    sign = app_id + text + str(salt) + secret_key
    sign = hashlib.md5(sign.encode()).hexdigest()

    # 判断是英文还是中文
    if '\u4e00' <= text[0] <= '\u9fff':
        from_lang = 'zh'
        to_lang = 'en'
    else:
        from_lang = 'en'
        to_lang = 'zh'

    params = {
        'q': text,
        'from': from_lang,
        'to': to_lang,
        'appid': app_id,
        'salt': salt,
        'sign': sign
    }

    response = requests.get(url, params=params)
    result = response.json()
    if 'trans_result' in result:
        return result['trans_result'][0]['dst']
    else:
        return "Error: Translation failed or response format changed."


if __name__ == "__main__":
    text_to_translate = "Hello, world"
    translated_text = translate_text(text_to_translate, from_lang='en', to_lang='zh')
    print(f"Translated Text: {translated_text}")
