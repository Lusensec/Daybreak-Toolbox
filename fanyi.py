import requests
import hashlib
import random

# 百度翻译凭证已从本文件外置到本地配置 config/baidu.py（含密钥，不随仓库分发）。
# 读取失败（如全新克隆未创建该文件）时置为 None，translate_text 会给出友好提示，
# 而不是让主程序在 import 阶段崩溃。
try:
    from config.baidu import BAIDU_FANYI_APP_ID, BAIDU_FANYI_SECRET_KEY
except Exception:
    BAIDU_FANYI_APP_ID = None
    BAIDU_FANYI_SECRET_KEY = None


def translate_text(text, from_lang='zh', to_lang='en'):
    app_id = BAIDU_FANYI_APP_ID
    secret_key = BAIDU_FANYI_SECRET_KEY

    if not app_id or not secret_key:
        return ("未配置百度翻译凭证：请在 config/baidu.py 中填写 "
                "BAIDU_FANYI_APP_ID 与 BAIDU_FANYI_SECRET_KEY 后重试。")

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
