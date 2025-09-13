import time
import tkinter as tk
import os
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk
import numpy as np
import cv2
from paddleocr import PaddleOCR
from pypinyin import lazy_pinyin
import pandas as pd
from AutoScriptor.recognition.rec import get_box_color
from AutoScriptor.utils.constant import cfg
from AutoScriptor.utils.box import Box
import traceback

class ImageEditor:
    """图片浏览与框选保存编辑器"""

    def __init__(self, image_paths):
        self.image_paths = image_paths
        self.index = 0
        self.rect = None
        self.crop_coords = None
        self.start_x = self.start_y = 0
        # self.scale = 0.5
        self.scale = 1
        self.window_width = 1280
        self.thr = 100  # 默认色差阈值
        
        # 初始化OCR引擎
        self.ocr_engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False, use_gpu=cfg["ocr.use_gpu"])

        self._init_root()
        self._init_variables()
        self._setup_ui()
        self._show_image()
        self._center_window()
        self.root.mainloop()

    def _init_root(self):
        """初始化主窗口"""
        self.root = tk.Tk()
        self.root.title("图片编辑与脚本编辑器")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)

    def _init_variables(self):
        """初始化变量"""
        self.free_x_var = tk.BooleanVar(master=self.root, value=True)
        self.free_y_var = tk.BooleanVar(master=self.root, value=True)
        self.only_ocr_var = tk.BooleanVar(master=self.root, value=False)
        self.center_var = tk.StringVar()
        self.box_var = tk.StringVar()

    def _setup_ui(self):
        """设置UI组件"""
        self._setup_canvas()
        self._setup_operation_frame()
        self._setup_info_frame()
        self._setup_button_frame()

    def _setup_canvas(self):
        """设置画布"""
        self.canvas = tk.Canvas(self.root, cursor="cross", width=self.window_width)
        self.canvas.pack(fill=tk.X)
        self.canvas.bind("<Button-1>", self._on_button_press)
        self.canvas.bind("<B1-Motion>", self._on_move_press)
        self.canvas.bind("<ButtonRelease-1>", self._on_button_release)

    def _setup_operation_frame(self):
        """设置操作区域"""
        op_frame_main = tk.Frame(self.root)
        op_frame_main.pack(fill=tk.X, pady=5)

        # 第一行控件
        op_frame_line1 = tk.Frame(op_frame_main)
        op_frame_line1.pack(fill=tk.X)

        tk.Label(op_frame_line1, text="名称：").pack(side=tk.LEFT, padx=5)
        self.name_entry = tk.Entry(op_frame_line1)
        self.name_entry.pack(side=tk.LEFT, padx=5)
        
        tk.Checkbutton(op_frame_line1, text="x轴范围自由", 
                      variable=self.free_x_var).pack(side=tk.LEFT, padx=5)
        tk.Checkbutton(op_frame_line1, text="y轴范围自由", 
                      variable=self.free_y_var).pack(side=tk.LEFT, padx=5)
        tk.Checkbutton(op_frame_line1, text="仅OCR", 
                      variable=self.only_ocr_var).pack(side=tk.LEFT, padx=5)

        # 阈值滑块
        tk.Label(op_frame_line1, text="阈值：").pack(side=tk.LEFT, padx=5)
        self.thr_scale = tk.Scale(op_frame_line1, from_=0, to=255, 
                                 orient=tk.HORIZONTAL, length=150,
                                 command=self.on_thr_change)
        self.thr_scale.set(self.thr)
        self.thr_scale.pack(side=tk.LEFT, padx=5)
        self.thr_scale.bind("<ButtonRelease-1>", lambda e: self.on_thr_release())

    def _setup_info_frame(self):
        """设置信息显示区域"""
        info_frame = tk.Frame(self.root)
        info_frame.pack(fill=tk.X, pady=2)
        
        # 中心点坐标框和复制按钮
        center_frame = tk.Frame(info_frame)
        center_frame.pack(side=tk.LEFT, padx=5)
        tk.Label(center_frame, text="中心点:").pack(side=tk.LEFT)
        self.center_entry = tk.Entry(center_frame, textvariable=self.center_var, width=18)
        self.center_entry.pack(side=tk.LEFT, padx=2)
        tk.Button(center_frame, text="复制", command=self.copy_center).pack(side=tk.LEFT)
        
        # Box坐标框和复制按钮
        box_frame = tk.Frame(info_frame)
        box_frame.pack(side=tk.LEFT, padx=5)
        tk.Label(box_frame, text="Box:").pack(side=tk.LEFT)
        self.box_entry = tk.Entry(box_frame, textvariable=self.box_var, width=24)
        self.box_entry.pack(side=tk.LEFT, padx=2)
        tk.Button(box_frame, text="复制", command=self.copy_box).pack(side=tk.LEFT)

    def _setup_button_frame(self):
        """设置按钮区域"""
        button_frame = tk.Frame(self.root)
        button_frame.pack(fill=tk.X, pady=5)
        
        buttons = [
            ("上一张", self.prev_image),
            ("下一张", self.next_image),
            ("保存选区", self.save_crop),
            ("退出", self.exit)
        ]
        
        for text, command in buttons:
            tk.Button(button_frame, text=text, command=command).pack(side=tk.LEFT, padx=5)

    def _center_window(self):
        """居中显示窗口"""
        self.root.update_idletasks()
        win_w = self.window_width
        win_h = self.root.winfo_height()
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = (sw - win_w) // 2
        y = (sh - win_h) // 2
        self.root.geometry(f"{win_w}x{win_h}+{x}+{y}")

    def _show_image(self):
        """显示当前图片"""
        path = self.image_paths[self.index]
        self.image = Image.open(path)
        ow, oh = self.image.size
        nw, nh = int(ow * self.scale), int(oh * self.scale)
        disp = self.image.resize((nw, nh), Image.LANCZOS)
        self.photo = ImageTk.PhotoImage(disp)
        self.canvas.config(width=nw, height=nh)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        self.rect = None
        self.crop_coords = None
        self.name_entry.delete(0, tk.END)

    def _on_button_press(self, e):
        """鼠标按下事件处理"""
        self.start_x, self.start_y = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y, outline='red'
        )

    def _on_move_press(self, e):
        """鼠标移动事件处理"""
        cx, cy = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        self.canvas.coords(self.rect, self.start_x, self.start_y, cx, cy)

    def _on_button_release(self, e):
        """鼠标释放事件处理"""
        ex, ey = self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)
        f = 1 / self.scale
        x0, y0 = int(self.start_x * f), int(self.start_y * f)
        x1, y1 = int(ex * f), int(ey * f)
        left, top, right, bottom = min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
        
        # 优化选区
        left, top, right, bottom = self.optimize_rect(left, top, right, bottom)
        
        # 更新显示
        self._update_selection_display(left, top, right, bottom)
        self._perform_ocr(left, top, right, bottom)
        self._update_coordinates(left, top, right, bottom)

    def _update_selection_display(self, left, top, right, bottom):
        """更新选区显示"""
        x0_s, y0_s = left * self.scale, top * self.scale
        x1_s, y1_s = right * self.scale, bottom * self.scale
        if self.rect:
            self.canvas.coords(self.rect, x0_s, y0_s, x1_s, y1_s)
        else:
            self.rect = self.canvas.create_rectangle(x0_s, y0_s, x1_s, y1_s, outline='red')
        self.crop_coords = (left, top, right, bottom)

    def _perform_ocr(self, left, top, right, bottom):
        """执行OCR识别"""
        cropped = self.image.crop((left, top, right, bottom))
        # 将PIL图像转换为numpy数组，然后转换为BGR格式供get_box_color使用
        import numpy as np
        import cv2
        pil_to_np = np.array(self.image)
        # PIL图像是RGB格式，需要转换为BGR格式
        bgr_image = cv2.cvtColor(pil_to_np, cv2.COLOR_RGB2BGR)
        print(get_box_color(bgr_image, Box(left, top, right - left, bottom - top)))
        
        try:
            # 转换为OpenCV格式
            cv_img = cv2.cvtColor(np.array(cropped), cv2.COLOR_RGB2BGR)
            # 执行OCR识别
            result = self.ocr_engine.ocr(cv_img, cls=True)
            print(result)
            if result and result[0]:
                # 获取第一个识别结果
                first_text = result[0][0][1][0]  # 获取文本内容
            else:
                first_text = ''
        except Exception as e:
            print(f"OCR错误: {e}")
            first_text = ''
        self.name_entry.delete(0, tk.END)
        self.name_entry.insert(0, first_text)

    def _update_coordinates(self, left, top, right, bottom):
        """更新坐标信息"""
        cx, cy = (left + right) // 2, (top + bottom) // 2
        w, h = right - left, bottom - top
        self.center_var.set(f"{cx},{cy}")
        self.box_var.set(f"Box({left},{top},{w},{h})")

    def optimize_rect(self, left, top, right, bottom):
        """优化选区"""
        if not (right > left and bottom > top):
            return left, top, right, bottom
            
        try:
            cropped = self.image.crop((left, top, right, bottom)).convert('RGB')
            arr = np.array(cropped, dtype=np.int16)
            h, w, _ = arr.shape

            # 计算色差
            dx = np.max(np.abs(arr[:, 1:, :] - arr[:, :-1, :]), axis=2)
            dy = np.max(np.abs(arr[1:, :, :] - arr[:-1, :, :]), axis=2)

            # 创建边缘掩码
            mask = np.zeros((h, w), dtype=bool)
            mask[:, 1:][dx > self.thr] = True
            mask[:, :-1][dx > self.thr] = True
            mask[1:, :][dy > self.thr] = True
            mask[:-1, :][dy > self.thr] = True

            # 找到边缘点
            ys, xs = np.where(mask)
            if ys.size == 0:
                return left, top, right, bottom

            # 计算新边界
            new_left = left + xs.min()
            new_top = top + ys.min()
            new_right = left + xs.max() + 1
            new_bottom = top + ys.max() + 1

            if new_right <= new_left or new_bottom <= new_top:
                return left, top, right, bottom
                
            return new_left, new_top, new_right, new_bottom

        except Exception as e:
            print(f"优化选区错误: {e}")
            return left, top, right, bottom

    def on_thr_change(self, val):
        """阈值改变事件处理"""
        self.thr = int(float(val))

    def on_thr_release(self):
        """阈值滑块释放事件处理"""
        if not self.crop_coords:
            return
        left, top, right, bottom = self.crop_coords
        new_left, new_top, new_right, new_bottom = self.optimize_rect(left, top, right, bottom)
        self._update_selection_display(new_left, new_top, new_right, new_bottom)
        self._perform_ocr(new_left, new_top, new_right, new_bottom)
        self._update_coordinates(new_left, new_top, new_right, new_bottom)

    def save_crop(self):
        """保存选区"""
        if not self.crop_coords:
            messagebox.showwarning("提示", "请先框选区域")
            return
            
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showwarning("提示", "名称不能为空")
            return

        # 处理名称，提取最后一个"-"后的字符作为text
        text = name
        if "-" in name:
            text = name.split("-")[-1]

        # 保存图片
        temp_dir = os.path.join(os.getcwd(), cfg["app"]["name"], "assets", "pic")
        os.makedirs(temp_dir, exist_ok=True)
        
        x0, y0, x1, y1 = self.crop_coords
        w, h = x1 - x0, y1 - y0
        cropped = self.image.crop((x0, y0, x1, y1))
        
        # 处理自由范围
        if self.free_x_var.get():
            x0, w = 0, 1280
        if self.free_y_var.get():
            y0, h = 0, 720

        # 生成文件名
        pinyin_name = ''.join(lazy_pinyin(name))
        fn = f"{pinyin_name}@{x0}#{y0}#{w}#{h}.png"
        sp = os.path.join(temp_dir, fn)

        # 如果不是仅OCR模式，则保存图片
        if not self.only_ocr_var.get():
            cropped.save(sp)
        else:
            fn = ""  # 仅OCR模式下不保存图片

        # 保存到CSV
        try:
            l = max(0, x0 - 10)
            t = max(0, y0 - 10)
            w2 = w + 20 if l + w + 20 <= 1280 else 1280 - l
            h2 = h + 20 if t + h + 20 <= 720 else 720 - t
            
            csv_path = os.path.join(os.getcwd(), cfg["app"]["name"], "assets", "config", "ui_map.csv")
            print(csv_path)
            try:
                df = pd.read_csv(csv_path, header=None, encoding='utf-8')
            except FileNotFoundError:
                df = pd.DataFrame(columns=range(7))
                
            df.loc[len(df)] = [name, text, l, t, w2, h2, fn]
            df.to_csv(csv_path, index=False, header=False, encoding='utf-8')
            
        except Exception as e:
            print(f"写入CSV失败: {e},traceback: {traceback.print_exc()}")
            
        messagebox.showinfo("提示", f"已保存: {sp if not self.only_ocr_var.get() else '仅保存配置'}")

    def prev_image(self):
        """显示上一张图片"""
        self.index = (self.index - 1) % len(self.image_paths)
        self._show_image()

    def next_image(self):
        """显示下一张图片"""
        self.index = (self.index + 1) % len(self.image_paths)
        self._show_image()

    def exit(self):
        """退出程序"""
        self.root.destroy()

    def copy_center(self):
        """复制中心点坐标到剪贴板"""
        self.root.clipboard_clear()
        self.root.clipboard_append(self.center_var.get())
        messagebox.showinfo("提示", "中心点坐标已复制到剪贴板")

    def copy_box(self):
        """复制Box坐标到剪贴板"""
        self.root.clipboard_clear()
        self.root.clipboard_append(self.box_var.get())
        messagebox.showinfo("提示", "Box坐标已复制到剪贴板")

def select_directory(directory="caps"):
    """选择图片目录"""
    root = tk.Tk()
    root.withdraw()
    default_dir = os.path.join(os.getcwd(), cfg["app_name"], 'output', directory)
    if not os.path.isdir(default_dir):
        default_dir = os.getcwd()
    dir_path = filedialog.askdirectory(title="选择图片目录", initialdir=default_dir)
    root.destroy()
    return dir_path

def get_image_files(dir_path):
    """获取目录中的图片文件"""
    exts = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
    return [
        os.path.join(dir_path, f)
        for f in os.listdir(dir_path)
        if f.lower().endswith(exts)
    ]

def launch_editor(mixctrl,is_screenshot=False):
    """启动编辑器"""
    root = tk.Tk()
    root.withdraw()
    root.destroy()

    if is_screenshot:
        try:
            img = mixctrl.screenshot()
        except Exception as e:
            tmp = tk.Tk()
            tmp.withdraw()
            messagebox.showerror("错误", f"截图失败: {e}")
            tmp.destroy()
            return

        temp_dir = os.path.join(os.getcwd())
        os.makedirs(temp_dir, exist_ok=True)
        ts = int(time.time())
        fp = os.path.join(temp_dir, f"screenshot_{ts}.png")
        cv2.imwrite(fp, img)
        ImageEditor([fp])
        os.remove(fp)
    else:
        dir_path = select_directory()
        if not dir_path:
            return
        files = get_image_files(dir_path)
        if not files:
            tmp = tk.Tk()
            tmp.withdraw()
            messagebox.showwarning("提示", "未找到任何图片文件")
            tmp.destroy()
            return
        ImageEditor(files)

if __name__ == "__main__":
    is_screenshot = messagebox.askyesno("选择模式", "是否立即截取屏幕图进行编辑？")
    launch_editor(None,is_screenshot)
