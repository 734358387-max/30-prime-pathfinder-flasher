import os
import sys
import time
import ctypes
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pywinusb.hid as hid

class FlasherApp:
    # --- USB 协议常量 ---
    TARGET_DEVICES = [
        (0x28E9, 0x028F),
        (0x0483, 0x5750),
        (0x28E9, 0x0285)
    ]
    
    # 唤醒暗号 (HOST -> DEVICE OUT)
    PAYLOADS = [
        [0xff, 0xff, 0x02, 0xf5, 0xf7] + [0x00] * 59,
        [0xff, 0xff, 0x02, 0xf8, 0xfa] + [0x00] * 59,
        [0xff, 0xff, 0x02, 0xf9, 0xfb] + [0x00] * 59,
    ]

    def __init__(self, root):
        self.root = root
        self.root.title("一键烧录与自动唤醒工具 v7.0")
        self.root.geometry("550x450")
        self.root.resizable(False, False)

        # Variables
        self.source_dir = tk.StringVar()
        self.target_drive = tk.StringVar()
        
        self.total_files = 0
        self.copied_files = 0
        
        self.is_flashing = False
        self.is_waking = False

        self.create_widgets()
        self.refresh_drives()

    def create_widgets(self):
        # 0. USB Wakeup Section (NEW v4)
        frame_wakeup = tk.LabelFrame(self.root, text="第一步: 准备硬件 (确保板子已插上)", padx=10, pady=10, fg="darkblue")
        frame_wakeup.pack(fill="x", padx=10, pady=10)
        
        self.btn_wakeup = tk.Button(frame_wakeup, text="点击：自动唤醒并激活U盘模式", 
                                   command=self.start_wakeup_thread, bg="#e1f5fe", font=("微软雅黑", 10, "bold"))
        self.btn_wakeup.pack(fill="x")

        # 1. Source Directory Selection
        frame_source = tk.LabelFrame(self.root, text="第二步: 选择资料源文件夹", padx=10, pady=10)
        frame_source.pack(fill="x", padx=10, pady=5)

        entry_source = tk.Entry(frame_source, textvariable=self.source_dir, state='readonly', width=50)
        entry_source.pack(side="left", padx=(0, 10))

        btn_browse = tk.Button(frame_source, text="浏览...", command=self.browse_source)
        btn_browse.pack(side="left")

        # 2. Target USB Selection
        frame_target = tk.LabelFrame(self.root, text="第三步: 选择目标 U盘", padx=10, pady=10)
        frame_target.pack(fill="x", padx=10, pady=5)

        self.combo_drives = ttk.Combobox(frame_target, textvariable=self.target_drive, state="readonly", width=47)
        self.combo_drives.pack(side="left", padx=(0, 10))
        
        btn_refresh = tk.Button(frame_target, text="刷新列表", command=self.refresh_drives)
        btn_refresh.pack(side="left")

        # 3. Progress and Status
        frame_status = tk.Frame(self.root)
        frame_status.pack(fill="x", padx=10, pady=10)
        
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(frame_status, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", pady=(0, 5))
        
        self.lbl_status = tk.Label(frame_status, text="就绪。请按顺序操作。", fg="blue", font=("微软雅黑", 9))
        self.lbl_status.pack(anchor="w")

        # 4. Flash Button
        self.btn_flash = tk.Button(self.root, text="一键烧录", font=("Arial", 16, "bold"), bg="#d32f2f", fg="white", 
                                   command=self.start_flash_thread, height=2)
        self.btn_flash.pack(fill="x", padx=10, pady=10)

    # --- 唤醒逻辑 ---
    def start_wakeup_thread(self):
        if self.is_waking or self.is_flashing: return
        self.is_waking = True
        self.btn_wakeup.config(state="disabled", text="正在由于设备通信...")
        threading.Thread(target=self.wakeup_process, daemon=True).start()

    def wakeup_process(self):
        try:
            self.update_status("正在寻找 HID 模式下的开发板...", color="orange")
            all_devices = hid.find_all_hid_devices()
            target_dev = None
            
            for dev in all_devices:
                for (vid, pid) in self.TARGET_DEVICES:
                    if dev.vendor_id == vid and dev.product_id == pid:
                        target_dev = dev
                        break
                if target_dev: break
            
            if not target_dev:
                self.update_status("未找到板子！请确认已插好且处于初始状态。", color="red")
                return

            self.update_status(f"找到设备! 正在发送唤醒指令...", color="blue")
            target_dev.open()
            
            reports = target_dev.find_output_reports() + target_dev.find_feature_reports()
            if not reports:
                self.update_status("协议错误: 未找到可通讯通道", color="red")
                return
            
            report = reports[0]
            for i, payload in enumerate(self.PAYLOADS):
                self.update_status(f"正在发送指令 {i+1}/3...")
                buffer = [0x00] + payload[:]
                # Pad to 65
                while len(buffer) < 65: buffer.append(0x00)
                report.set_raw_data(buffer[:65])
                report.send()
                time.sleep(0.4) # 等待设备响应
            
            # Aggressively close the HID device to free the port for the U-disk mode
            target_dev.close()
            del target_dev
            
            self.update_status("唤醒指令发送完毕! 正在请求系统刷新硬件设备...", color="green")
            
            # Request Windows to rescan PnP devices (broadcasting WM_DEVICECHANGE)
            try:
                HWND_BROADCAST = 0xFFFF
                WM_DEVICECHANGE = 0x0219
                # 0x0007 == Dbt_devnodes_changed
                ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_DEVICECHANGE, 0x0007, 0, 2, 1000, None)
            except:
                pass
            
            # Wait 8.5 seconds for the new USB interface to initialize and mount before refreshing
            time.sleep(8.5)
            self.refresh_drives()
            if self.target_drive.get() and "未检测" not in self.target_drive.get():
                self.update_status("✅ 唤醒且系统识别成功！U盘已就绪。", color="green")
            else:
                self.update_status("指令已发，但未自动挂载。请尝试手动点刷新。", color="orange")

        except Exception as e:
            self.update_status(f"唤醒异常: {str(e)}", color="red")
        finally:
            self.is_waking = False
            self.root.after(0, lambda: self.btn_wakeup.config(state="normal", text="点击：自动唤醒并激活U盘模式"))

    # --- 烧录逻辑 (原版保持) ---
    def browse_source(self):
        if self.is_flashing: return
        folder = filedialog.askdirectory(title="选择要烧录的根目录")
        if folder:
            self.source_dir.set(folder)

    def get_removable_drives(self):
        drives = []
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
            if bitmask & 1:
                drive_path = f"{letter}:\\"
                if ctypes.windll.kernel32.GetDriveTypeW(drive_path) == 2:
                    volume_name_buf = ctypes.create_unicode_buffer(1024)
                    ctypes.windll.kernel32.GetVolumeInformationW(
                        ctypes.c_wchar_p(drive_path),
                        volume_name_buf,
                        ctypes.sizeof(volume_name_buf),
                        None, None, None, None, 0
                    )
                    vol_name = volume_name_buf.value or "可移动磁盘"
                    drives.append(f"{letter}: [{vol_name}]")
            bitmask >>= 1
        return drives

    def refresh_drives(self):
        if self.is_flashing: return
        new_values = self.get_removable_drives()
        self.combo_drives['values'] = new_values
        if new_values:
            self.combo_drives.current(0)
        else:
            self.target_drive.set("")
            self.combo_drives.set("未检测到U盘... 请点击唤醒或刷新")

    def update_status(self, text, color="black", progress=None):
        def _update():
            self.lbl_status.config(text=text, fg=color)
            if progress is not None:
                self.progress_var.set(progress)
        self.root.after(0, _update)

    def enable_ui(self, enable):
        state = "normal" if enable else "disabled"
        def _update():
            self.btn_flash.config(state=state)
            self.btn_wakeup.config(state=state)
            self.combo_drives.config(state=state)
        self.root.after(0, _update)

    def count_files(self, path):
        count = 0
        for root, dirs, files in os.walk(path):
            count += len(files)
        return count

    def start_flash_thread(self):
        if self.is_flashing: return
        src = self.source_dir.get()
        target = self.target_drive.get()
        
        if not src:
            messagebox.showwarning("提示", "请先选择资料源文件夹！")
            return
        if not target or "未检测" in target:
            messagebox.showwarning("提示", "请先选择目标U盘！")
            return
            
        target_path = target.split(":")[0] + ":\\"
        msg = f"确定清空并烧录到 {target} 吗？"
        if not messagebox.askyesno("确认", msg): return

        self.is_flashing = True
        self.enable_ui(False)
        self.btn_flash.config(text="执行中...")
        threading.Thread(target=self.flash_process, args=(src, target_path), daemon=True).start()

    def flash_process(self, src, target_path):
        try:
            self.update_status("正在清空目标盘...", color="blue")
            for item in os.listdir(target_path):
                if item.upper() == "SYSTEM VOLUME INFORMATION": continue
                item_path = os.path.join(target_path, item)
                try:
                    if os.path.isfile(item_path):
                        os.chmod(item_path, 0o777)
                        os.remove(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path, ignore_errors=True)
                except: pass

            self.total_files = self.count_files(src)
            self.copied_files = 0
            
            for root, dirs, files in os.walk(src):
                rel = os.path.relpath(root, src)
                dest = target_path if rel == "." else os.path.join(target_path, rel)
                os.makedirs(dest, exist_ok=True)
                for f in files:
                    shutil.copy2(os.path.join(root, f), os.path.join(dest, f))
                    self.copied_files += 1
                    pct = (self.copied_files / self.total_files) * 100
                    self.update_status(f"同步中... {self.copied_files}/{self.total_files}", progress=pct)

            self.update_status("✅ 烧录成功！", color="green", progress=100)
            self.root.after(0, lambda: messagebox.showinfo("成功", "文件已全部同步。"))
        except Exception as e:
            self.update_status(f"失败: {str(e)}", color="red")
        finally:
            self.is_flashing = False
            self.enable_ui(True)
            self.root.after(0, lambda: self.btn_flash.config(text="一键烧录"))

if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit(1)
    root = tk.Tk()
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except: pass
    app = FlasherApp(root)
    root.mainloop()
