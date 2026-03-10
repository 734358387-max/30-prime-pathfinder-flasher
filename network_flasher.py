import os
import sys
import time
import ctypes
import shutil
import threading
import tempfile
import urllib.request
import urllib.parse
import zipfile
import hashlib
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
        self.root.title("一键烧录与自动唤醒工具 v8.3")
        self.root.geometry("550x500")
        self.root.resizable(False, False)

        # Variables
        self.source_mode = tk.IntVar(value=1) # 1: Local, 2: Cloud
        self.source_dir = tk.StringVar()
        self.target_drive = tk.StringVar()
        
        # Cloud Configuration (Dynamic)
        self.cloud_bucket_url = "https://lsbot-sw-page.oss-cn-shenzhen.aliyuncs.com"
        self.cloud_presets = {} # Map filename to full URL dynamically
        
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

        # 1. Source Selection (HYBRID UI v8)
        frame_source = tk.LabelFrame(self.root, text="第二步: 选择资料源", padx=10, pady=10)
        frame_source.pack(fill="x", padx=10, pady=5)
        
        # Local Mode UI
        frame_local = tk.Frame(frame_source)
        frame_local.pack(fill="x", pady=2)
        tk.Radiobutton(frame_local, text="本地文件夹:", variable=self.source_mode, value=1, command=self.update_source_ui).pack(side="left")
        
        self.entry_source = tk.Entry(frame_local, textvariable=self.source_dir, state='readonly', width=40)
        self.entry_source.pack(side="left", padx=(5, 5))
        
        self.btn_browse = tk.Button(frame_local, text="浏览...", command=self.browse_source)
        self.btn_browse.pack(side="left")

        # Cloud Mode UI
        frame_cloud = tk.Frame(frame_source)
        frame_cloud.pack(fill="x", pady=2)
        tk.Radiobutton(frame_cloud, text="云端固件库:", variable=self.source_mode, value=2, command=self.update_source_ui).pack(side="left")
        
        self.combo_cloud = ttk.Combobox(frame_cloud, state="readonly", width=47)
        self.combo_cloud.set("正在获取云端列表...")
        self.combo_cloud.pack(side="left", padx=(5, 5))
        
        self.btn_refresh = tk.Button(frame_cloud, text="刷新", command=self.fetch_cloud_list_thread)
        self.btn_refresh.pack(side="left")

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
        
        self.update_source_ui()
        self.fetch_cloud_list_thread()

    def fetch_cloud_list_thread(self):
        self.combo_cloud['values'] = []
        self.combo_cloud.set("正在获取云端列表...")
        self.btn_refresh.config(state="disabled")
        threading.Thread(target=self._fetch_cloud_list, daemon=True).start()
        
    def _fetch_cloud_list(self):
        try:
            # Check for index.txt list file
            index_url = f"{self.cloud_bucket_url}/index.txt"
            req = urllib.request.Request(index_url)
            # Send a fake User-Agent to avoid generic blocks
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
            
            with urllib.request.urlopen(req, timeout=5) as response:
                raw_data = response.read()
                
            # Try multiple encodings in case Windows Notepad saved it weirdly
            try:
                text_data = raw_data.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text_data = raw_data.decode('utf-16')
                except UnicodeDecodeError:
                    text_data = raw_data.decode('gbk', errors='ignore')
            
            files = []
            for line in text_data.splitlines():
                line = line.strip()
                if not line: continue
                parts = line.split('|')
                filename = parts[0].strip()
                expected_md5 = parts[1].strip().lower() if len(parts) > 1 else None
                
                if filename.lower().endswith('.zip'):
                    files.append(filename)
                    encoded_name = urllib.parse.quote(filename)
                    url = f"{self.cloud_bucket_url}/{encoded_name}"
                    self.cloud_presets[filename] = (url, expected_md5)
                    
            if not files:
                self.root.after(0, lambda: self._update_combo_ui(["暂无有效固件包"], "未在索引文件中找到固件"))
            else:
                self.root.after(0, lambda: self._update_combo_ui(files, files[0]))
                
        except urllib.error.HTTPError as e:
            if e.code == 404:
                self.root.after(0, lambda: self._update_combo_ui([], "云端未放置 index.txt 配置文件！"))
            else:
                self.root.after(0, lambda: self._update_combo_ui([], f"云端获取错误: {e.code}"))
        except Exception as e:
            self.root.after(0, lambda: self._update_combo_ui([], f"网络异常: {str(e)}"))
        finally:
            self.root.after(0, lambda: self.btn_refresh.config(state="normal"))

    def _update_combo_ui(self, values, current_val):
        self.combo_cloud['values'] = values
        self.combo_cloud.set(current_val)

    def update_source_ui(self):
        if self.source_mode.get() == 1:
            self.entry_source.config(state="normal")
            self.btn_browse.config(state="normal")
            self.combo_cloud.config(state="disabled")
        else:
            self.entry_source.config(state="disabled")
            self.btn_browse.config(state="disabled")
            self.combo_cloud.config(state="normal")

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
        target = self.target_drive.get()
        
        mode = self.source_mode.get()
        src_path = None
        cloud_url = None
        expected_md5 = None
        
        if mode == 1:
            src_path = self.source_dir.get()
            if not src_path:
                messagebox.showwarning("提示", "请先选择本地资料源文件夹！")
                return
        else:
            selected_preset = self.combo_cloud.get()
            cloud_info = self.cloud_presets.get(selected_preset)
            if not cloud_info:
                messagebox.showwarning("提示", "请先选择有效的云端固件！")
                return
            cloud_url, expected_md5 = cloud_info
                
        if not target or "未检测" in target:
            messagebox.showwarning("提示", "请先选择目标U盘！")
            return
            
        target_path = target.split(":")[0] + ":\\"
        msg = f"确定清空并烧录到 {target} 吗？\n(模式: {'本地' if mode == 1 else '云端'})"
        if not messagebox.askyesno("确认", msg): return

        self.is_flashing = True
        self.enable_ui(False)
        self.btn_flash.config(text="执行中...")
        
        if mode == 1:
            threading.Thread(target=self.flash_process, args=(src_path, target_path), daemon=True).start()
        else:
            threading.Thread(target=self.network_flash_process, args=(cloud_url, expected_md5, target_path), daemon=True).start()

    def network_flash_process(self, url, expected_md5, target_path):
        temp_dir = tempfile.mkdtemp(prefix="flasher_")
        zip_path = os.path.join(temp_dir, "downloaded.zip")
        extract_path = os.path.join(temp_dir, "extracted")
        
        try:
            self.update_status("正在连接云端下载固件...", color="blue", progress=0)
            
            def report_hook(count, block_size, total_size):
                if total_size > 0:
                    pct = (count * block_size * 100) / total_size
                    pct = min(100, pct)
                    self.update_status(f"下载中... {pct:.1f}%", progress=pct)
            
            # 1. Download ZIP
            urllib.request.urlretrieve(url, zip_path, reporthook=report_hook)
            
            # 1.5 Verify MD5 if provided
            if expected_md5:
                self.update_status("正在进行 MD5 固件安全校验...", color="blue")
                hash_md5 = hashlib.md5()
                with open(zip_path, "rb") as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        hash_md5.update(chunk)
                computed_md5 = hash_md5.hexdigest()
                
                if computed_md5 != expected_md5:
                    raise Exception(f"固件指纹校验失败！\n预期: {expected_md5}\n实际: {computed_md5}\n\n文件在传输过程中可能已损坏。")
            
            # 2. Extract ZIP
            self.update_status("校验通过，正在解压...", color="orange", progress=0)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                total_items = len(zip_ref.namelist())
                extracted = 0
                for item in zip_ref.namelist():
                    zip_ref.extract(item, extract_path)
                    extracted += 1
                    pct = (extracted / total_items) * 100
                    self.update_status(f"解压中... {extracted}/{total_items}", progress=pct)
            
            # 3. Handle potential root folder wrapper in zip
            source_dir = extract_path
            extracted_items = os.listdir(extract_path)
            if len(extracted_items) == 1 and os.path.isdir(os.path.join(extract_path, extracted_items[0])):
                source_dir = os.path.join(extract_path, extracted_items[0])
            
            # 4. Hand off to the standard flash process
            self.flash_process(source_dir, target_path, is_from_network=True)
            
        except Exception as e:
            self.update_status(f"网络下载或解压失败: {str(e)}", color="red")
            self.is_flashing = False
            self.enable_ui(True)
            self.root.after(0, lambda: self.btn_flash.config(text="一键烧录"))
        finally:
            # Always cleanup the temp directory after flashing or on failure
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except: pass

    def flash_process(self, src, target_path, is_from_network=False):
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
                    src_file = os.path.join(root, f)
                    dest_file = os.path.join(dest, f)
                    try:
                        shutil.copy2(src_file, dest_file)
                    except OSError as e:
                        if getattr(e, 'errno', None) == 22:
                            # Fallback: file system might not support setting some metadata/timestamps
                            shutil.copy(src_file, dest_file)
                        else:
                            raise
                    
                    self.copied_files += 1
                    pct = (self.copied_files / self.total_files) * 100
                    self.update_status(f"同步中... {self.copied_files}/{self.total_files}", progress=pct)

            self.update_status("✅ 烧录成功！", color="green", progress=100)
            self.root.after(0, lambda: messagebox.showinfo("成功", "文件已全部同步。"))
        except Exception as e:
            self.update_status(f"失败: {str(e)}", color="red")
        finally:
            if not is_from_network:
                self.is_flashing = False
                self.enable_ui(True)
                self.root.after(0, lambda: self.btn_flash.config(text="一键烧录"))
            else:
                # If network, let the network thread handle the UI unlock after cleanup
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
