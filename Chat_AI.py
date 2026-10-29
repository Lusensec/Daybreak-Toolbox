import requests

from fun import *
from openai import OpenAI

def kimi_ai(msg, ai_api):
    from openai import OpenAI
    global global_history

    client = OpenAI(
        api_key=ai_api,
        base_url="https://api.moonshot.cn/v1",
    )

    # 系统提示词（可自定义）
    system_prompt = {
        "role": "system",
        "content": "您是 Kimi，由 Moonshot AI 提供的人工智能助手，并且是一位高深莫测的网络安全专家。请用中文回答用户问题。"
    }

    # 构建完整消息列表（系统提示 + 历史对话 + 当前消息）
    messages = [system_prompt]
    messages.extend(global_history)
    messages.append({"role": "user", "content": msg})

    try:
        completion = client.chat.completions.create(
            model="moonshot-v1-128k",
            messages=messages,
            temperature=0.3,
        )

        # 获取AI回复
        ai_reply = completion.choices[0].message.content

        # 更新历史记录（添加用户消息和AI回复）
        global_history.extend([
            {"role": "user", "content": msg},
            {"role": "assistant", "content": ai_reply}
        ])

        # 限制历史记录长度（moonshot-v1-128k支持长上下文，这里限制为最近20轮）
        if len(global_history) > 100:
            global_history = global_history[-20:]

        return f"**Kimi: **{ai_reply}"

    except Exception as e:
        print(f"发生错误：{e}")
        return f"**Kimi: **请求失败（{str(e)}）"  # 错误时返回原历史记录


# 改成OpenAI写法：
#def tongyi_openai(msg, ai_api):
#    from openai import OpenAI
#
#    global global_history
#
#    client = Client(
#        api_key=ai_api,
#        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
#    )
#
#    messages = [
#        {"role": "system", "content": "请用中文回答用户问题"}
#    ]
#    messages.extend(global_history)
#    messages.append({"role": "user", "content": msg})
#
#    resp = client.chat.completions.create(
#        model="qwen-turbo",
#        messages=messages,
#    )
#
#    ai_reply = resp.choices[0].message.content
#
#    global_history.extend([
#        {"role": "user", "content": msg},
#        {"role": "assistant", "content": ai_reply}
#    ])
#
#    if len(global_history) > 100:
#        global_history = global_history[-100:]
#
#    return f"**通义千问: **{ai_reply}"
    
    
def tongyi(msg, ai_api):
    import dashscope
    from dashscope import Generation
    global global_history  # 声明使用全局变量

    # 设置API密钥（如果环境变量未配置）
    dashscope.api_key = ai_api

    # 构建消息列表（系统提示 + 历史对话 + 当前消息）
    messages = [
        {"role": "system", "content": "请用中文回答用户问题"}
    ]
    messages.extend(global_history)
    messages.append({"role": "user", "content": msg})

    # 调用DashScope API（注意：qwen_turbo需使用messages格式）
    response = Generation.call(
        model=dashscope.Generation.Models.qwen_turbo,
        messages=messages  # 使用messages参数而非prompt
    )

    # 获取AI回复
    ai_reply = response.output['text']

    # 更新历史记录（添加用户消息和AI回复）
    global_history.extend([
        {"role": "user", "content": msg},
        {"role": "assistant", "content": ai_reply}
    ])

    # 限制历史记录长度（例如保留最近10轮对话）
    if len(global_history) > 100:  # 10轮对话（每轮含用户+AI两条消息）
        global_history = global_history[-100:]

    return f"**通义千问: **{ai_reply}"

def deepseek(msg, ai_api):
    global global_history  # 声明使用全局变量

    client = OpenAI(api_key=ai_api, base_url="https://api.deepseek.com")

    messages = [
        {"role": "system", "content": "You are a helpful assistant. 请用中文回答用户问题。"},
        *global_history,  # 展开历史
        {"role": "user", "content": msg},
    ]

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        stream=False
    )

    ai_reply = response.choices[0].message.content

    # 更新全局历史（添加用户消息和AI回复）
    global_history.extend([
        {"role": "user", "content": msg},
        {"role": "assistant", "content": ai_reply}
    ])

    # 限制历史长度（例如最近10轮对话）
    if len(global_history) > 100:  # 10轮对话（每轮2条消息）
        global_history = global_history[-100:]

    return f"**deepseek: **{ai_reply}"

def ollama(msg, ai_api):
    global global_history  # 声明使用全局变量

    # 如果 ai_api 的最后是/，则去除
    if ai_api.endswith('/'):
        ai_api = ai_api[:-1]

    url = ai_api
    model = requests.get(url + '/api/tags', timeout=60).json()['models'][0]['model']

    headers = {"Content-Type": "application/json"}

    # 构建消息列表，包含历史对话和当前消息
    messages = [
        {
            "role": "system",
            "content": "请用中文回答下面问题，语言要简洁明了，层次分明。"
        }
    ]

    # 添加历史对话
    messages.extend(global_history)

    # 添加用户当前消息
    messages.append({
        "role": "user",
        "content": "请用中文回答用户问题。" + msg
    })

    data = {
        "model": model,  # 模型选择
        "options": {
            "temperature": 1.  # 为0表示不让模型自由发挥，输出结果相对较固定，>0的话，输出的结果会比较放飞自我
        },
        "stream": False,  # 非流式输出
        "messages": messages  # 包含上下文的对话列表
    }

    response = requests.post(url + "/api/chat", json=data, headers=headers, timeout=60).json()

    # 将AI的回复添加到历史对话中
    ai_reply = {
        "role": "assistant",
        "content": response['message']['content']
    }
    global_history.extend([
        {"role": "user", "content": msg},
        ai_reply
    ])

    # 限制历史记录长度，防止过大
    if len(global_history) > 100:  # 保留最近10轮对话(每轮包含用户消息和AI回复)
        global_history = global_history[-100:]

    return "**ollama: **" + response['message']['content']

def zhipu(msg, ai_api):
    from zhipuai import ZhipuAI
    global global_history  # 声明使用全局变量

    # 创建客户端
    zhipu_client = ZhipuAI(api_key=ai_api)

    # 系统提示词（可自定义）
    system_prompt = {
        "role": "system",
        "content": "你是智谱清言（GLM-4），一个由智谱AI开发的人工智能助手。请用中文回答用户问题。"
    }

    # 构建完整消息列表（系统提示 + 历史对话 + 当前消息）
    messages = [system_prompt]
    messages.extend(global_history)
    messages.append({"role": "user", "content": msg})

    try:
        response = zhipu_client.chat.completions.create(
            model="glm-4-air",  # 或 glm-4
            messages=messages,
            stream=False,
        )

        # 获取AI回复
        ai_reply = response.choices[0].message.content.strip()

        # 更新历史记录（添加用户消息和AI回复）
        global_history.extend([
            {"role": "user", "content": msg},
            {"role": "assistant", "content": ai_reply}
        ])

        # 限制历史记录长度（GLM-4上下文窗口为128K，这里限制为最近10轮对话）
        if len(global_history) > 100:  # 10轮对话（每轮含用户+AI两条消息）
            global_history = global_history[-100:]

        return f"**智谱清言: **{ai_reply}"

    except Exception as e:
        print(f"发生错误：{e}")
        return f"**智谱清言: **请求失败（{str(e)}）"  # 错误时返回原历史记录

def ai_main(ai_name,msg):
    global ai_json

    if ai_name == "kimi_ai":
        # 调用kimi 接口
        return kimi_ai(msg=msg, ai_api=get_ai_json_one_api(ai_name=ai_name))
    elif ai_name == "通义千问":
        return tongyi(msg=msg, ai_api=get_ai_json_one_api(ai_name=ai_name))
    elif ai_name == "智谱清言":
        return zhipu(msg=msg, ai_api=get_ai_json_one_api(ai_name=ai_name))
    elif ai_name == "deepseek_api":
        return deepseek(msg=msg, ai_api=get_ai_json_one_api(ai_name=ai_name))
    elif ai_name == "ollama":
        return ollama(msg=msg, ai_api=get_ai_json_one_api(ai_name=ai_name))
