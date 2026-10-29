import base64
import json
import urllib.parse

import requests
from bs4 import BeautifulSoup


def base64_encode(data):
    """
    Base64编码
    :param data: 要编码的数据(bytes或str)
    :return: 编码后的字符串
    """
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.b64encode(data).decode('utf-8')

def base64_decode(encoded_data):
    """
    Base64解码
    :param encoded_data: 要解码的字符串
    :return: 解码后的原始数据(bytes)
    """
    return base64.b64decode(encoded_data.encode('utf-8'))

def url_encode(data):
    """
    URL编码
    :param data: 要编码的字符串
    :return: 编码后的字符串
    """
    return urllib.parse.quote(data)

def url_decode(encoded_data):
    """
    URL解码
    :param encoded_data: 要解码的字符串
    :return: 解码后的原始字符串
    """
    return urllib.parse.unquote(encoded_data)

def unicode_encode(text):
    """
    Unicode编码
    :param text: 要编码的字符串
    :return: Unicode编码后的字符串
    """
    return ''.join([f'\\u{ord(c):04x}' for c in text])

def unicode_decode(encoded_text):
    """
    Unicode解码
    :param encoded_text: Unicode编码的字符串
    :return: 解码后的原始字符串
    """
    import re
    return re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), encoded_text)

def utf8_encode(text):
    """
    UTF-8编码
    :param text: 要编码的字符串
    :return: UTF-8编码后的字符串
    """
    return text.encode('utf-8')

def utf8_decode(text, flag=False):
    """
    UTF-8解码
    :param encoded_text: UTF-8编码的字符串
    :return: 解码后的原始字符串
    """
    url = "http://www.mytju.com/classCode/tools/messyCodeRecover.asp"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0) Gecko/20100101 Firefox/141.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2",
        "Accept-Encoding": "gzip, deflate",
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "http://www.mytju.com",
        "DNT": "1",
        "Connection": "keep-alive",
        "Referer": "http://www.mytju.com/classCode/tools/messyCodeRecover.asp",
        "Upgrade-Insecure-Requests": "1",
        "Priority": "u=0, i",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
    }

    Cookies = {
        "ASPSESSIONIDAABTDBAT": "KANAMJPBBHKGBKNGBPDGNOHL"
    }

    data = {
        "myAction": "autoRecover",
        "inputStr": f"{text}"
    }

    response = requests.post(url, headers=headers, cookies=Cookies, data=data)
    response.encoding = 'utf-8'

    soup = BeautifulSoup(response.text, 'html.parser')
    table = soup.find_all('table')[1]
    yuanwen = []

    try:
        if flag:
            for tr in table.find_all('tr'):
                yuanwen.append(tr.find_all('td')[2].text.strip())
        else:
            for tr in table.find_all('tr'):
                td_all = tr.find_all('td')
                if td_all[1].text == "UTF-8":
                    yuanwen.append(td_all[2].text.strip())
    except:
        pass

    # 将数组转换为字符串，元素间用换行符连接
    result = "\n".join(yuanwen) if yuanwen else "无法转换"
    return result

def json_format(text):
    # 先尝试解析，如果是 Python 字典字符串（含 ''' 或 """），先转成标准 JSON
    text = text.strip()

    # 标准 JSON 处理
    try:
        return json.dumps(json.loads(text), indent=4, ensure_ascii=False)
    except:
        try:
            import ast
            return json.dumps(ast.literal_eval(text), indent=4, ensure_ascii=False)
        except:
            return json.dumps(eval(text), indent=4, ensure_ascii=False)


def md5_encode(text):
    """
    MD5编码
    :param text: 要编码的字符串
    :return: MD5编码后的字符串
    """
    import hashlib
    return hashlib.md5(text.encode('utf-8')).hexdigest()

if __name__ == "__main__":
    # 示例数据
    wrong_str = '锘垮崡闃'  # 这是 GBK 数据被错误地用 UTF-8 解码后的结果

    try:
        # 尝试直接使用原始字符串
        if isinstance(wrong_str, str):
            # 先尝试GBK解码
            try:
                correct_str = wrong_str.encode('latin1').decode('gbk')
                print(f"GBK解码结果: {correct_str}")
            except (UnicodeEncodeError, UnicodeDecodeError):
                # 如果失败，尝试其他常见编码
                for encoding in ['cp1252', 'iso-8859-1', 'utf-8']:
                    try:
                        correct_str = wrong_str.encode('latin1').decode(encoding)
                        print(f"使用{encoding}解码结果: {correct_str}")
                        break
                    except (UnicodeEncodeError, UnicodeDecodeError):
                        continue
                else:
                    print("无法解码字符串，请检查原始编码")
    except Exception as e:
        print(f"发生错误: {e}")

    print(md5_encode("1"))
