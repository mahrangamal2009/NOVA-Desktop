# -*- coding: utf-8 -*-
"""
NOVA Desktop 3.0
A cautious Windows dashboard: monitoring, temporary/cache cleanup,
startup/program shortcuts, network rates, notes, RAM Manager, and DNS Manager.
"""
import os
import sys
import json
import time
import shutil
import subprocess
import tempfile
import threading
import logging
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

try:
    import psutil
except ImportError:
    psutil = None

APP_NAME = "NOVA Desktop"
APP_VERSION = "3.0"
APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "NOVA Desktop"
APP_DIR.mkdir(parents=True, exist_ok=True)
NOTES_FILE = APP_DIR / "notes.json"
LOG_FILE = APP_DIR / "nova.log"

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)
log = logging.getLogger("nova")

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

BG = "#0b0b12"
PANEL = "#151522"
PANEL2 = "#1d1b2b"
PURPLE = "#9b72ff"
TEXT = "#f1efff"
MUTED = "#aaa5bd"
GREEN = "#7ce0b2"
ORANGE = "#ffca78"


def fmt_bytes(value):
    value = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def safe_delete(path):
    """Delete a file/folder only when it is inside an explicitly selected cache path."""
    try:
        p = Path(path)
        if p.is_symlink():
            p.unlink(missing_ok=True)
        elif p.is_file():
            p.unlink(missing_ok=True)
        elif p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        return True
    except (PermissionError, OSError):
        return False


def cache_targets():
    local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    temp = Path(tempfile.gettempdir())
    targets = [
        ("ملفات المستخدم المؤقتة", temp),
        ("كاش DirectX Shaders", local / "D3DSCache"),
        ("كاش الصور المصغرة", local / "Microsoft" / "Windows" / "Explorer"),
    ]
    win_temp = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Temp"
    targets.append(("ملفات Windows المؤقتة (المتاح فقط)", win_temp))
    return targets


def scan_path(path, thumbnail_only=False):
    total = 0
    entries = []
    try:
        if not path.exists():
            return total, entries
        if thumbnail_only:
            for p in path.glob("thumbcache*"):
                try:
                    if p.is_file():
                        total += p.stat().st_size
                        entries.append(p)
                except OSError:
                    pass
            return total, entries
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
            for name in files:
                p = Path(root) / name
                try:
                    if p.is_symlink():
                        continue
                    st = p.stat()
                    if st.st_file_attributes & getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0):
                        continue
                    total += st.st_size
                    entries.append(p)
                except (OSError, AttributeError):
                    continue
    except (PermissionError, OSError):
        pass
    return total, entries


def run_cmd(cmd, timeout=15):
    """Run a command safely with an argument list (no shell). Returns (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "انتهت مهلة الأمر."
    except FileNotFoundError:
        return -1, "", "الأمر غير موجود."
    except Exception as exc:
        return -1, "", str(exc)


def get_standby_cache():
    """Try to read Windows standby/cache memory via PowerShell. Returns dict or None."""
    ps_cmd = [
        "powershell", "-NoProfile", "-Command",
        "$core = (Get-Counter '\\Memory\\Standby Cache Core Bytes' -ErrorAction SilentlyContinue).CounterSamples.CookedValue;"
        "$normal = (Get-Counter '\\Memory\\Standby Cache Normal Priority Bytes' -ErrorAction SilentlyContinue).CounterSamples.CookedValue;"
        "$reserve = (Get-Counter '\\Memory\\Standby Cache Reserve Bytes' -ErrorAction SilentlyContinue).CounterSamples.CookedValue;"
        "$cache = (Get-Counter '\\Memory\\Cache Bytes' -ErrorAction SilentlyContinue).CounterSamples.CookedValue;"
        "[PSCustomObject]@{Core=$core; Normal=$normal; Reserve=$reserve; Cache=$cache} | ConvertTo-Json",
    ]
    try:
        rc, out, err = run_cmd(ps_cmd, timeout=10)
        if rc == 0 and out.strip():
            data = json.loads(out.strip())
            return {
                "core": float(data.get("Core", 0) or 0),
                "normal": float(data.get("Normal", 0) or 0),
                "reserve": float(data.get("Reserve", 0) or 0),
                "cache": float(data.get("Cache", 0) or 0),
            }
    except Exception:
        pass
    return None


class NovaApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("1120x720")
        self.root.minsize(900, 600)
        self.root.configure(bg=BG)
        self.last_net = None
        self.net_time = None
        self.current_page = None
        self.ram_auto = True
        self.startup_tree = None
        self._style()
        self._layout()
        self.show_page("overview")
        self.refresh_stats()

    def refresh_stats(self):
        if psutil:
            psutil.cpu_percent(interval=None)
        # No further scheduling needed; called during init.

    def _style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", background=PANEL, foreground=TEXT, fieldbackground=PANEL,
                        rowheight=28, borderwidth=0)
        style.configure("Treeview.Heading", background=PANEL2, foreground=TEXT, relief="flat")
        style.map("Treeview", background=[("selected", "#49377a")], foreground=[("selected", "white")])
        style.configure("TProgressbar", troughcolor=PANEL2, background=PURPLE, bordercolor=PANEL2)

    def _layout(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=24, pady=(18, 10))
        tk.Label(header, text="NOVA", bg=BG, fg=TEXT, font=("Segoe UI", 25, "bold")).pack(side="left")
        tk.Label(header, text=f"  DESKTOP {APP_VERSION}", bg=BG, fg=PURPLE, font=("Segoe UI", 10, "bold")).pack(side="left", pady=(10, 0))
        self.status = tk.Label(header, text="● جاهز", bg=BG, fg=GREEN, font=("Segoe UI", 10))
        self.status.pack(side="right", pady=12)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=(4, 18))
        nav = tk.Frame(body, bg=PANEL, width=205)
        nav.pack(side="left", fill="y", padx=(0, 14))
        nav.pack_propagate(False)
        tk.Label(nav, text="مساحة العمل", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(anchor="e", padx=18, pady=(22, 12))
        items = [
            ("overview", "نظرة عامة"),
            ("monitor", "مراقبة النظام"),
            ("cleaner", "تنظيف الملفات والكاش"),
            ("memory", "مدير الذاكرة RAM"),
            ("dns", "مدير DNS"),
            ("programs", "البرامج"),
            ("startup", "برامج الابتداء"),
            ("network", "الشبكة"),
            ("notes", "الملاحظات"),
        ]
        for key, label in items:
            tk.Button(nav, text=label, command=lambda k=key: self.show_page(k),
                      bg=PANEL, fg=TEXT, activebackground=PANEL2, activeforeground="white",
                      relief="flat", bd=0, anchor="e", padx=18, pady=12,
                      font=("Segoe UI", 10), cursor="hand2").pack(fill="x", padx=8, pady=2)
        tk.Label(nav, text=f"{APP_NAME} • v{APP_VERSION}", bg=PANEL, fg="#716b85",
                 font=("Segoe UI", 8)).pack(side="bottom", pady=16)
        self.content = tk.Frame(body, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

    def clear(self):
        for w in self.content.winfo_children():
            w.destroy()

    def heading(self, title, desc=""):
        tk.Label(self.content, text=title, bg=BG, fg=TEXT, font=("Segoe UI", 21, "bold")).pack(anchor="e", pady=(8, 2))
        if desc:
            tk.Label(self.content, text=desc, bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="e", pady=(0, 14))

    def card(self, parent, title, value, note=""):
        f = tk.Frame(parent, bg=PANEL, padx=18, pady=16)
        tk.Label(f, text=title, bg=PANEL, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="e")
        v = tk.Label(f, text=value, bg=PANEL, fg=TEXT, font=("Segoe UI", 22, "bold"))
        v.pack(anchor="e", pady=(7, 2))
        if note:
            tk.Label(f, text=note, bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="e")
        return f, v

    def show_page(self, page):
        self.current_page = page
        self.clear()
        if page == "overview":
            self.page_overview()
        elif page == "monitor":
            self.page_monitor()
        elif page == "cleaner":
            self.page_cleaner()
        elif page == "memory":
            self.page_ram()
        elif page == "dns":
            self.page_dns()
        elif page == "programs":
            self.page_programs()
        elif page == "startup":
            self.page_startup()
        elif page == "network":
            self.page_network()
        elif page == "notes":
            self.page_notes()

    def _stats(self):
        if not psutil:
            return None
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        return cpu, mem, disk

    def page_overview(self):
        self.heading("نظرة عامة", "ملخص سريع لحالة جهازك")
        if not psutil:
            self._need_psutil()
            return
        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x", pady=8)
        cpu, mem, disk = self._stats()
        for title, value, note in [
            ("المعالج CPU", f"{cpu:.0f}%", "الاستخدام الحالي"),
            ("الذاكرة RAM", f"{mem.percent:.0f}%", f"{fmt_bytes(mem.used)} مستخدم"),
            ("مساحة قرص النظام", fmt_bytes(disk.free), f"من {fmt_bytes(disk.total)} متاح"),
        ]:
            c, _ = self.card(row, title, value, note)
            c.pack(side="left", fill="both", expand=True, padx=5)
        box = tk.Frame(self.content, bg=PANEL, padx=20, pady=18)
        box.pack(fill="x", pady=14)
        tk.Label(box, text="ملاحظات مهمة", bg=PANEL, fg=TEXT, font=("Segoe UI", 13, "bold")).pack(anchor="e")
        tips = [
            "ويندوز يدير الذاكرة RAM تلقائيًا؛ NOVA يعرض أكثر البرامج استهلاكًا ويساعدك على إغلاقها يدويًا.",
            "تنظيف الكاش يزيل ملفات مؤقتة محددة فقط، وقد يعيد بعض البرامج إنشاءها لاحقًا.",
            "درجات الحرارة تعتمد على الحساسات التي يتيحها الجهاز؛ قد لا تظهر كل الحساسات على بعض أجهزة AMD.",
            "مدير DNS جديد في الإصدار 3.0 لمسح كاش DNS وإعادة تعيين عناوين DNS إلى التلقائي.",
        ]
        for t in tips:
            tk.Label(box, text="• " + t, bg=PANEL, fg=MUTED, font=("Segoe UI", 10), anchor="e", justify="right").pack(fill="x", pady=5)
        tk.Button(self.content, text="تحديث الآن", command=lambda: self.show_page("overview"),
                  bg=PURPLE, fg="white", relief="flat", padx=18, pady=9).pack(anchor="e", pady=8)

    def page_monitor(self):
        self.heading("مراقبة النظام", "استخدام المعالج والذاكرة والقرص ودرجات الحرارة المتاحة")
        if not psutil:
            self._need_psutil()
            return
        wrap = tk.Frame(self.content, bg=BG)
        wrap.pack(fill="x")
        self.monitor_labels = {}
        for key, label in [("cpu", "CPU"), ("ram", "RAM"), ("disk", "Disk"), ("temp", "Temperature")]:
            c, v = self.card(wrap, label, "—")
            c.pack(side="left", fill="both", expand=True, padx=5, pady=5)
            self.monitor_labels[key] = v
        tk.Label(self.content, text="درجة الحرارة قد لا تكون متاحة من Windows على كل الأجهزة. لا يتم التحكم في المراوح من NOVA.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9), wraplength=760, justify="right").pack(anchor="e", pady=12)
        self.update_monitor()

    def read_temp(self):
        try:
            cmd = ["powershell", "-NoProfile", "-Command",
                   "(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop | Select-Object -First 1 -ExpandProperty CurrentTemperature)"]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=3, creationflags=CREATE_NO_WINDOW)
            raw = out.stdout.strip()
            if out.returncode == 0 and raw.isdigit():
                c = int(raw) / 10 - 273.15
                if 0 < c < 120:
                    return f"{c:.0f} °C (ACPI)"
        except Exception:
            pass
        return "غير متاحة"

    def update_monitor(self):
        if self.current_page != "monitor" or not psutil:
            return
        cpu, mem, disk = self._stats()
        self.monitor_labels["cpu"].config(text=f"{cpu:.0f}%")
        self.monitor_labels["ram"].config(text=f"{mem.percent:.0f}%")
        self.monitor_labels["disk"].config(text=f"{disk.percent:.0f}%")
        self.monitor_labels["temp"].config(text=self.read_temp())
        self.root.after(2500, self.update_monitor)

    def page_cleaner(self):
        self.heading("تنظيف الملفات والكاش", "فحص مجلدات مؤقتة آمنة نسبيًا قبل الحذف")
        note = "لن نحذف ملفات التنزيلات أو المستندات أو كلمات المرور أو بيانات تسجيل الدخول. أغلق البرامج قبل التنظيف."
        tk.Label(self.content, text=note, bg=BG, fg=ORANGE, font=("Segoe UI", 10), wraplength=760, justify="right").pack(anchor="e", pady=(0, 12))
        self.clean_vars = {}
        self.clean_rows = tk.Frame(self.content, bg=BG)
        self.clean_rows.pack(fill="x")
        self.clean_total = tk.Label(self.content, text="لم يتم الفحص بعد", bg=BG, fg=TEXT, font=("Segoe UI", 12, "bold"))
        self.clean_total.pack(anchor="e", pady=12)
        buttons = tk.Frame(self.content, bg=BG)
        buttons.pack(anchor="e")
        tk.Button(buttons, text="فحص الكاش", command=self.scan_caches, bg=PURPLE, fg="white", relief="flat", padx=16, pady=9).pack(side="right", padx=4)
        self.delete_btn = tk.Button(buttons, text="حذف المحدد", command=self.delete_caches, bg="#653f75", fg="white", relief="flat", padx=16, pady=9, state="disabled")
        self.delete_btn.pack(side="right", padx=4)
        self.cache_results = []

    def scan_caches(self):
        for w in self.clean_rows.winfo_children():
            w.destroy()
        self.cache_results = []
        total = 0
        for name, path in cache_targets():
            thumb = "الصور المصغرة" in name
            size, files = scan_path(path, thumbnail_only=thumb)
            total += size
            var = tk.BooleanVar(value=True)
            row = tk.Frame(self.clean_rows, bg=PANEL, padx=12, pady=10)
            row.pack(fill="x", pady=3)
            tk.Checkbutton(row, text=f"{name} — {fmt_bytes(size)} ({len(files)} ملف)",
                           variable=var, bg=PANEL, fg=TEXT, selectcolor=PANEL2,
                           activebackground=PANEL, activeforeground=TEXT, font=("Segoe UI", 10)).pack(anchor="e")
            self.cache_results.append((name, files, var, size))
        self.clean_total.config(text=f"الإجمالي القابل للفحص: {fmt_bytes(total)}")
        self.delete_btn.config(state="normal")

    def delete_caches(self):
        selected = [(n, fs, s) for n, fs, v, s in self.cache_results if v.get()]
        if not selected:
            messagebox.showinfo("NOVA", "حدد عنصرًا واحدًا على الأقل.")
            return
        estimate = sum(s for _, _, s in selected)
        if not messagebox.askyesno("تأكيد الحذف", f"سيحاول NOVA حذف الملفات المحددة فقط.\nالحجم التقريبي: {fmt_bytes(estimate)}\nقد يتم تخطي الملفات المستخدمة. هل تريد المتابعة؟"):
            return
        deleted = skipped = 0
        for name, files, _ in selected:
            for p in files:
                if safe_delete(p):
                    deleted += 1
                else:
                    skipped += 1
        messagebox.showinfo("اكتمل التنظيف", f"تمت معالجة الملفات.\nملفات حُذفت/أزيلت: {deleted}\nملفات تم تخطيها أو تعذر حذفها: {skipped}")
        self.scan_caches()

    # ==================== RAM MANAGER ====================

    def page_ram(self):
        self.heading("مدير الذاكرة RAM", "معلومات الذاكرة واستهلاك العمليات على جهازك")
        if not psutil:
            self._need_psutil()
            return

        mem = psutil.virtual_memory()
        standby = get_standby_cache()

        row = tk.Frame(self.content, bg=BG)
        row.pack(fill="x", pady=6)
        cards = [
            ("إجمالي الذاكرة", fmt_bytes(mem.total), "الذاكرة الفعلية المثبتة"),
            ("الذاكرة المستخدمة", fmt_bytes(mem.used), "المستخدمة من قبل النظام والتطبيقات"),
            ("الذاكرة المتاحة", fmt_bytes(mem.available), "متاحة للاستخدام الفوري"),
            ("نسبة الاستخدام", f"{mem.percent:.1f}%", "نسبة استخدام الذاكرة الإجمالية"),
        ]
        if standby:
            total_standby = standby["core"] + standby["normal"] + standby["reserve"]
            cards.append(("الذاكرة المخزنة مؤقتًا (استعداد)", fmt_bytes(total_standby), "تحت إدارة ويندوز تلقائيًا"))
        else:
            cards.append(("الذاكرة المخزنة مؤقتًا", "غير متاحة", "بيانات استعداد ويندوز غير متاحة"))

        for title, value, note in cards:
            c, _ = self.card(row, title, value, note)
            c.pack(side="left", fill="both", expand=True, padx=5)

        pb_frame = tk.Frame(self.content, bg=BG)
        pb_frame.pack(fill="x", pady=(10, 6))
        tk.Label(pb_frame, text="استخدام الذاكرة", bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="e")
        self.ram_pb = ttk.Progressbar(pb_frame, orient="horizontal", mode="determinate", maximum=100)
        self.ram_pb.pack(fill="x", pady=(4, 0))
        self.ram_pb["value"] = mem.percent

        ctrl = tk.Frame(self.content, bg=BG)
        ctrl.pack(anchor="e", pady=(6, 10))
        self.ram_auto_var = tk.BooleanVar(value=True)
        tk.Checkbutton(ctrl, text="تحديث تلقائي", variable=self.ram_auto_var, bg=BG, fg=TEXT,
                       selectcolor=PANEL2, activebackground=BG, activeforeground=TEXT,
                       font=("Segoe UI", 10), command=self._toggle_ram_auto).pack(side="right", padx=4)
        tk.Button(ctrl, text="تحديث الآن", command=self._refresh_ram_now, bg=PURPLE, fg="white",
                  relief="flat", padx=16, pady=8).pack(side="right", padx=4)

        tk.Label(self.content, text="أكثر العمليات استهلاكًا للذاكرة", bg=BG, fg=TEXT,
                 font=("Segoe UI", 12, "bold")).pack(anchor="e", pady=(14, 4))
        cols = ("name", "pid", "mem")
        self.ram_tree = ttk.Treeview(self.content, columns=cols, show="headings", height=14)
        for col, title, width in [("name", "البرنامج", 340), ("pid", "PID", 80), ("mem", "استهلاك RAM", 160)]:
            self.ram_tree.heading(col, text=title, command=lambda c=col: self._sort_ram(c))
            self.ram_tree.column(col, width=width, anchor="center")
        self.ram_tree.pack(fill="both", expand=True, pady=5)

        pbtn = tk.Frame(self.content, bg=BG)
        pbtn.pack(anchor="e", pady=8)
        tk.Button(pbtn, text="تحديث القائمة", command=self._refresh_ram_now, bg=PURPLE, fg="white",
                  relief="flat", padx=14, pady=7).pack(side="right", padx=4)
        tk.Button(pbtn, text="فتح مدير المهام", command=lambda: subprocess.Popen("taskmgr.exe"),
                  bg=PANEL2, fg=TEXT, relief="flat", padx=14, pady=7).pack(side="right", padx=4)

        box = tk.Frame(self.content, bg=PANEL, padx=20, pady=16)
        box.pack(fill="x", pady=(16, 0))
        tk.Label(box, text="حول إدارة الذاكرة في ويندوز", bg=PANEL, fg=TEXT, font=("Segoe UI", 12, "bold")).pack(anchor="e")
        expl = [
            "ويندوز يدير ذاكرة الوصول العشوائي (RAM) تلقائيًا ويحررها عند الحاجة.",
            "الذاكرة \"المستخدمة\" تشمل الذاكرة التي تشغل بها البرامج والنظام حاليًا.",
            "الذاكرة \"المتاحة\" تشمل الذاكرة الحرة بالإضافة إلى الذاكرة المخزنة مؤقتًا التي يمكن تحريرها فورًا.",
            "الذاكرة \"المخزنة مؤقتًا (استعداد)\" هي بيانات تخزنها ويندوز لتسريع الوصول إليها، وتحرر تلقائيًا عند الحاجة.",
            "لا يوجد زر \"مسح RAM\" آمن وموثوق؛ إغلاق البرامج التي لا تستخدمها هو الطريقة العملية والآمنة.",
            "لا يحاول NOVA إنهاء عمليات النظام أو عمليات حرجة أو أي تطبيق تلقائيًا.",
        ]
        for t in expl:
            tk.Label(box, text="• " + t, bg=PANEL, fg=MUTED, font=("Segoe UI", 10), anchor="e", justify="right").pack(fill="x", pady=3)

        self._populate_ram_processes()
        self._schedule_ram_refresh()

    def _toggle_ram_auto(self):
        self.ram_auto = self.ram_auto_var.get()
        if self.ram_auto:
            self._schedule_ram_refresh()

    def _schedule_ram_refresh(self):
        if self.current_page == "memory" and self.ram_auto:
            self.root.after(5000, self._refresh_ram_now)

    def _refresh_ram_now(self):
        if not psutil or self.current_page != "memory":
            return
        try:
            mem = psutil.virtual_memory()
            self.ram_pb["value"] = mem.percent
            self._populate_ram_processes()
            if self.ram_auto and self.current_page == "memory":
                self._schedule_ram_refresh()
        except Exception as exc:
            log.error("RAM refresh failed: %s", exc)

    def _populate_ram_processes(self):
        if not psutil or self.current_page != "memory":
            return
        if not hasattr(self, "ram_tree"):
            return
        for item in self.ram_tree.get_children():
            self.ram_tree.delete(item)
        processes = []
        for p in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                info = p.info
                rss = info["memory_info"].rss if info.get("memory_info") else 0
                processes.append((rss, info.get("name") or "Unknown", info.get("pid")))
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
        for rss, name, pid in sorted(processes, key=lambda x: x[0], reverse=True)[:30]:
            self.ram_tree.insert("", "end", values=(name, pid, fmt_bytes(rss)))

    def _sort_ram(self, col):
        if self.current_page != "memory":
            return
        data = []
        for child in self.ram_tree.get_children(""):
            vals = self.ram_tree.item(child, "values")
            data.append((vals, child))
        try:
            if col == "mem":
                data.sort(key=lambda x: float(x[0][2].split()[0]) if x[0][2] else 0, reverse=True)
            elif col == "pid":
                data.sort(key=lambda x: int(x[0][1]) if str(x[0][1]).isdigit() else 0, reverse=True)
            else:
                data.sort(key=lambda x: str(x[0][0]), reverse=True)
        except Exception:
            pass
        for i, (vals, child) in enumerate(data):
            self.ram_tree.move(child, "", i)

    # ==================== DNS MANAGER ====================

    def page_dns(self):
        self.heading("مدير DNS", "إدارة كاش DNS وإعدادات خوادم DNS على ويندوز")

        box1 = tk.Frame(self.content, bg=PANEL, padx=20, pady=16)
        box1.pack(fill="x", pady=(0, 14))
        tk.Label(box1, text="أ. مسح كاش DNS", bg=PANEL, fg=TEXT, font=("Segoe UI", 13, "bold")).pack(anchor="e", pady=(0, 6))
        tk.Label(box1, text="ينفذ أمر ipconfig /flushdns لمسح كاش DNS المحلي على الجهاز.", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 10), wraplength=740, justify="right").pack(anchor="e", pady=(0, 10))
        self.dns_flush_result = tk.Label(box1, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 10), wraplength=740, justify="right")
        self.dns_flush_result.pack(anchor="e", pady=(0, 8))
        tk.Button(box1, text="مسح كاش DNS الآن", command=self._confirm_flush_dns, bg=PURPLE, fg="white",
                  relief="flat", padx=18, pady=9).pack(anchor="e")

        box2 = tk.Frame(self.content, bg=PANEL, padx=20, pady=16)
        box2.pack(fill="both", expand=True)
        tk.Label(box2, text="ب. إعادة تعيين إعدادات DNS إلى تلقائي (DHCP)", bg=PANEL, fg=TEXT, font=("Segoe UI", 13, "bold")).pack(anchor="e", pady=(0, 6))
        tk.Label(box2, text="يقوم باستعادة عناوين خوادم DNS إلى التلقائي عبر DHCP لمُوصل الشبكة المحدد فقط. لا يتم تغيير عناوين IP.",
                 bg=PANEL, fg=MUTED, font=("Segoe UI", 10), wraplength=740, justify="right").pack(anchor="e", pady=(0, 10))

        cols = ("name", "index", "status", "dns")
        self.dns_tree = ttk.Treeview(box2, columns=cols, show="headings", height=8)
        for col, title, width in [("name", "اسم المُوصل", 220), ("index", "الفهرس", 70), ("status", "الحالة", 120), ("dns", "خوادم DNS الحالية", 300)]:
            self.dns_tree.heading(col, text=title)
            self.dns_tree.column(col, width=width, anchor="center")
        self.dns_tree.pack(fill="both", expand=True, pady=(0, 10))
        self.dns_tree.bind("<<TreeviewSelect>>", lambda e: self._on_dns_select())

        dbtn = tk.Frame(box2, bg=PANEL)
        dbtn.pack(anchor="e", pady=(0, 8))
        tk.Button(dbtn, text="تحديث قائمة المُوصلات", command=self._refresh_dns_adapters, bg=PANEL2, fg=TEXT,
                  relief="flat", padx=14, pady=7).pack(side="right", padx=4)
        self.dns_reset_btn = tk.Button(dbtn, text="إعادة تعيين DNS للمحدد", command=self._confirm_reset_dns,
                                       bg="#653f75", fg="white", relief="flat", padx=14, pady=7, state="disabled")
        self.dns_reset_btn.pack(side="right", padx=4)

        self.dns_reset_result = tk.Label(box2, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 10), wraplength=740, justify="right")
        self.dns_reset_result.pack(anchor="e", pady=(0, 6))

        self._refresh_dns_adapters()

        warn = tk.Frame(self.content, bg=PANEL, padx=20, pady=12)
        warn.pack(fill="x")
        tk.Label(warn, text="⚠ تحذير: إعادة تعيين DNS ستستبدل عناوين DNS المخصصة بعناوين تلقائية. لا يتم إجراء أي تغيير عند تشغيل البرنامج.",
                 bg=PANEL, fg=ORANGE, font=("Segoe UI", 10), wraplength=740, justify="right").pack(anchor="e")

    def _get_dns_servers(self, index):
        rc, out, err = run_cmd([
            "powershell", "-NoProfile", "-Command",
            f"Get-DnsClientServerAddress -InterfaceIndex {index} | Select-Object ServerAddresses | ConvertTo-Json -Depth 2",
        ], timeout=10)
        if rc != 0 or not out.strip():
            return "غير متاح"
        try:
            data = json.loads(out.strip())
            if isinstance(data, dict):
                data = [data]
            addrs = []
            for d in data:
                sa = d.get("ServerAddresses", [])
                if isinstance(sa, list):
                    addrs.extend(str(a) for a in sa if a)
            return ", ".join(addrs) if addrs else "تلقائي"
        except Exception:
            return "غير متاح"

    def _refresh_dns_adapters(self):
        if not hasattr(self, "dns_tree"):
            return
        for item in self.dns_tree.get_children():
            self.dns_tree.delete(item)
        self.dns_reset_btn.config(state="disabled")

        rc, out, err = run_cmd([
            "powershell", "-NoProfile", "-Command",
            "Get-NetAdapter | Select-Object Name, InterfaceIndex, Status | ConvertTo-Json -Depth 2",
        ], timeout=15)
        if rc != 0 or not out.strip():
            log.error("DNS adapter discovery failed: %s", err)
            return
        try:
            adapters = json.loads(out.strip())
            if isinstance(adapters, dict):
                adapters = [adapters]
            for a in adapters:
                name = a.get("Name", "Unknown")
                index = a.get("InterfaceIndex", "—")
                status = a.get("Status", "—")
                dns_str = self._get_dns_servers(index)
                self.dns_tree.insert("", "end", values=(name, index, status, dns_str))
        except Exception as exc:
            log.error("Failed to parse DNS adapters: %s", exc)

    def _on_dns_select(self):
        if self.dns_tree.selection():
            self.dns_reset_btn.config(state="normal")
        else:
            self.dns_reset_btn.config(state="disabled")

    def _confirm_flush_dns(self):
        if not messagebox.askyesno("تأكيد", "هل تريد مسح كاش DNS باستخدام الأمر ipconfig /flushdns؟"):
            return
        self.status.config(text="● جاري مسح DNS...", fg=ORANGE)
        self.dns_flush_result.config(text="جاري التنفيذ...", fg=MUTED)
        threading.Thread(target=self._flush_dns_thread, daemon=True).start()

    def _flush_dns_thread(self):
        rc, out, err = run_cmd(["ipconfig", "/flushdns"], timeout=15)
        msg = out.strip() or err.strip()
        if rc == 0:
            msg = "تم مسح كاش DNS بنجاح.\n" + msg
            self.root.after(0, lambda: self.dns_flush_result.config(text=msg, fg=GREEN))
        else:
            msg = "فشل مسح كاش DNS.\n" + (err or msg)
            self.root.after(0, lambda: self.dns_flush_result.config(text=msg, fg=ORANGE))
        self.root.after(0, lambda: self.status.config(text="● جاهز", fg=GREEN))

    def _confirm_reset_dns(self):
        sel = self.dns_tree.selection()
        if not sel:
            messagebox.showinfo("NOVA", "حدد موصل شبكة واحد من القائمة.")
            return
        vals = self.dns_tree.item(sel[0], "values")
        name = vals[0]
        index = vals[1]
        current_dns = vals[3]
        warning = (
            f"تم تحديد الموصل: {name} (الفهرس: {index})\n"
            f"عناوين DNS الحالية: {current_dns or 'غير محددة / تلقائي'}\n\n"
            "هذه العملية ستستعيد عناوين DNS إلى التلقائي (DHCP).\n"
            "سيتم استبدال عناوين DNS المخصصة. لن يتم تغيير عناوين IP.\n"
            "قد تحتاج إلى صلاحيات مسؤول.\n\n"
            "هل تريد المتابعة؟"
        )
        if not messagebox.askyesno("تأكيد إعادة تعيين DNS", warning):
            return
        self.status.config(text="● جاري إعادة تعيين DNS...", fg=ORANGE)
        self.dns_reset_result.config(text="جاري التنفيذ...", fg=MUTED)
        threading.Thread(target=self._reset_dns_thread, args=(index,), daemon=True).start()

    def _reset_dns_thread(self, index):
        rc, out, err = run_cmd([
            "powershell", "-NoProfile", "-Command",
            f"Set-DnsClientServerAddress -InterfaceIndex {index} -ResetServerAddresses",
        ], timeout=15)
        msg = out.strip() or err.strip()
        if rc == 0:
            msg = "تم إعادة تعيين DNS بنجاح.\n" + msg
            self.root.after(0, lambda: self.dns_reset_result.config(text=msg, fg=GREEN))
            self.root.after(0, self._refresh_dns_adapters)
        else:
            msg = "فشل إعادة تعيين DNS.\n" + (err or msg)
            self.root.after(0, lambda: self.dns_reset_result.config(text=msg, fg=ORANGE))
        self.root.after(0, lambda: self.status.config(text="● جاهز", fg=GREEN))

    # ==================== EXISTING PAGES ====================

    def page_programs(self):
        self.heading("البرامج", "اختصارات قائمة Start؛ إزالة البرامج تتم من إعدادات Windows")
        tree = ttk.Treeview(self.content, columns=("name", "path"), show="headings", height=16)
        tree.heading("name", text="اسم البرنامج")
        tree.heading("path", text="مسار الاختصار")
        tree.column("name", width=250)
        tree.column("path", width=560)
        tree.pack(fill="both", expand=True, pady=5)
        folders = [Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
                   Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs"]
        for folder in folders:
            if folder.exists():
                for p in folder.rglob("*.lnk"):
                    tree.insert("", "end", values=(p.stem, str(p)))

        def open_selected():
            sel = tree.selection()
            if not sel:
                return
            path = tree.item(sel[0], "values")[1]
            try:
                os.startfile(path)
            except Exception as e:
                messagebox.showerror("NOVA", str(e))

        bar = tk.Frame(self.content, bg=BG)
        bar.pack(anchor="e", pady=8)
        tk.Button(bar, text="تشغيل المحدد", command=open_selected, bg=PURPLE, fg="white", relief="flat", padx=14, pady=8).pack(side="right", padx=4)
        tk.Button(bar, text="إعدادات التطبيقات", command=lambda: os.startfile("ms-settings:appsfeatures"), bg=PANEL2, fg=TEXT, relief="flat", padx=14, pady=8).pack(side="right", padx=4)

    def page_network(self):
        self.heading("مراقبة الشبكة", "سرعة الإرسال والاستقبال الحالية على الجهاز، وليست اختبار سرعة الإنترنت")
        self.net_recv = tk.Label(self.content, text="↓ 0 KB/s", bg=PANEL, fg=GREEN, font=("Segoe UI", 24, "bold"), padx=24, pady=22)
        self.net_send = tk.Label(self.content, text="↑ 0 KB/s", bg=PANEL, fg=PURPLE, font=("Segoe UI", 24, "bold"), padx=24, pady=22)
        self.net_recv.pack(fill="x", pady=6)
        self.net_send.pack(fill="x", pady=6)
        self.net_note = tk.Label(self.content, text="يتم تحديث القراءة كل ثانية.", bg=BG, fg=MUTED, font=("Segoe UI", 9))
        self.net_note.pack(anchor="e", pady=8)
        self.update_network()

    def update_network(self):
        if self.current_page != "network" or not psutil:
            return
        now = time.time()
        counters = psutil.net_io_counters()
        current = (counters.bytes_recv, counters.bytes_sent)
        if self.last_net is not None:
            dt = max(now - self.net_time, 0.01)
            self.net_recv.config(text=f"↓ {fmt_bytes((current[0] - self.last_net[0]) / dt)}/s")
            self.net_send.config(text=f"↑ {fmt_bytes((current[1] - self.last_net[1]) / dt)}/s")
        self.last_net, self.net_time = current, now
        self.root.after(1000, self.update_network)

    def page_notes(self):
        self.heading("الملاحظات السريعة", "تُحفظ الملاحظات محليًا على جهازك")
        box = tk.Text(self.content, bg=PANEL, fg=TEXT, insertbackground=TEXT, relief="flat",
                      font=("Segoe UI", 12), wrap="word", padx=14, pady=14)
        box.pack(fill="both", expand=True, pady=6)
        try:
            if NOTES_FILE.exists():
                data = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
                box.insert("1.0", data.get("text", ""))
        except Exception:
            pass

        def save():
            NOTES_FILE.write_text(json.dumps({"text": box.get("1.0", "end-1c")}, ensure_ascii=False, indent=2), encoding="utf-8")
            messagebox.showinfo("NOVA", "تم حفظ الملاحظات.")

        tk.Button(self.content, text="حفظ", command=save, bg=PURPLE, fg="white", relief="flat", padx=18, pady=9).pack(anchor="e", pady=8)

    def page_startup(self):
        self.heading("برامج الابتداء", "البرامج التي تبدأ تلقائيًا عند التشغيل")
        box = tk.Frame(self.content, bg=PANEL, padx=20, pady=16)
        box.pack(fill="x", pady=(0, 14))
        tk.Label(box, text="برامج الابتداء", bg=PANEL, fg=TEXT, font=("Segoe UI", 13, "bold")).pack(anchor="e", pady=(0, 6))
        tk.Label(box, text="البرامج التي تبدأ تلقائيًا عند تشغيل ويندوز.", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 10), wraplength=740, justify="right").pack(anchor="e", pady=(0, 10))

        cols = ("name", "path", "enabled")
        self.startup_tree = ttk.Treeview(self.content, columns=cols, show="headings", height=12)
        for col, title, width in [("name", "اسم البرنامج", 340), ("path", "المسار", 200), ("enabled", "مفعول", 80)]:
            self.startup_tree.heading(col, text=title)
            self.startup_tree.column(col, width=width, anchor="center")
        self.startup_tree.pack(fill="both", expand=True, pady=(0, 10))

        dbtn = tk.Frame(box, bg=PANEL)
        dbtn.pack(anchor="e", pady=(0, 8))
        tk.Button(dbtn, text="تحديث القائمة", command=self._refresh_startup, bg=PANEL2, fg=TEXT,
                  relief="flat", padx=14, pady=7).pack(side="right", padx=4)
        tk.Button(dbtn, text="إعدادات التطبيقات", command=lambda: os.startfile("ms-settings:appsfeatures"), bg=PANEL2, fg=TEXT,
                  relief="flat", padx=14, pady=8).pack(side="right", padx=4)

        self._populate_startup_processes()
        self._schedule_startup_refresh()

    def fetch_startup_entries(self):
        """Return list of dicts {name, path, enabled}."""
        entries = []
        local = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        temp = Path(tempfile.gettempdir())
        targets = cache_targets()
        found_paths = set()
        for name, path in cache_targets():
            thumb = "الصور المصغرة" in name
            if path.exists():
                if path.is_dir():
                    first_file = next((p for p in path.iterdir() if p.is_file()), None)
                    if first_file:
                        entries.append({"name": first_file.name, "path": str(first_file), "enabled": False})
                else:
                    entries.append({"name": name, "path": str(path), "enabled": False})
        # Registry fallback
        reg_key = r"Software\Microsoft\Windows\Startup"
        try:
            import winreg
            keys = {}
            try:
                hkey = winreg.OpenKey(r"HKEY_CURRENT_USER", reg_key)
                for i in range(winreg.QueryInfoKeys(hkey)):
                    fval, _ = winreg.QueryValueEx(hkey, i)
                    if fval and "=" in fval:
                        parts = fval.split("=")
                        name = parts[0].strip().split("/")[0]
                        value = parts[1].strip()
                        keys[name] = value
                winreg.CloseKey(hkey)
            except Exception:
                pass
            for name, value in keys.items():
                if name not in found_paths:
                    entries.append({"name": name, "path": value, "enabled": bool(value.strip()) if isinstance(value, str) else True})
        except Exception:
            pass
        return entries

    def _toggle_startup(self, idx, val):
        item = self.startup_tree.item(idx, "selected") if self.current_page == "startup" else None
        if item is None:
            messagebox.showinfo("NOVA", "اختر عنصرًا واحدًا من قائمة البرامج الابتدائية.")
            return
        current_enabled = item.get("enabled", False)
        new_enabled = val
        if current_enabled != new_enabled:
            item['values'][2] = str(new_enabled)
            self.root.after(0, lambda: self.startup_tree.reindex())
        else:
            self.startup_tree.move(item, "", 0)
        sel = self.startup_tree.selection()
        if sel:
            self.dns_reset_btn.config(state="normal")
        self.root.after(0, lambda: self.status.config(text="● جاهز", fg=GREEN))

    def _schedule_startup_refresh(self):
        if self.current_page == "startup" and self.ram_auto:
            self.root.after(5000, self._refresh_startup_now)

    def _refresh_startup_now(self):
        if not psutil or self.current_page != "startup":
            return
        entries = self.fetch_startup_entries()
        for e in entries:
            row = tk.Frame(self.content, bg=BG)
            row.pack(fill="x", pady=5)
            c = tk.Checkbutton(row, text=f"{e['name']} — {e['path']}", variable=e['enabled'],
                               bg=PANEL, fg=TEXT, selectcolor=PANEL2, activebackground=PANEL, activeforeground=TEXT,
                               font=("Segoe UI", 10)).pack(anchor="e")
            tk.Button(row, text="تشغيل المحدد", command=lambda p=e['path']: self.open_selected(p),
                      bg=PURPLE, fg="white", relief="flat", padx=14, pady=7).pack(side="left", fill="x", expand=True)
        self.root.after(3000, self.refresh_startup_now)

    def open_selected(self, path):
        # Launch selected program
        if path and os.path.exists(path):
            try:
                os.startfile(path)
            except Exception as e:
                messagebox.showerror("NOVA", str(e))

    def refresh_startup(self):
        if not psutil or self.current_page != "startup":
            return
        entries = self.fetch_startup_entries()
        for e in entries:
            row = tk.Frame(self.content, bg=BG)
            row.pack(fill="x", pady=5)
            c = tk.Checkbutton(row, text=f"{e['name']} — {e['path']}", variable=e['enabled'],
                               bg=PANEL, fg=TEXT, selectcolor=PANEL2, activebackground=PANEL, activeforeground=TEXT,
                               font=("Segoe UI", 10)).pack(anchor="e")
            tk.Button(row, text="تشغيل المحدد", command=lambda p=e['path']: self.open_selected(p),
                      bg=PURPLE, fg="white", relief="flat", padx=14, pady=7).pack(side="left", fill="x", expand=True)
        self.root.after(3000, self.refresh_startup_now)

    # ==================== EXISTING PAGES ====================
    
    def page_programs(self):
        if psutil:
            psutil.cpu_percent(interval=None)
        self.root.after(3000, self.refresh_stats)


    def refresh_stats(self):
        if psutil:
            psutil.cpu_percent(interval=None)
        self.root.after(3000, self.refresh_stats)

    def main():
        root = tk.Tk()
        app = NovaApp(root)
        root.mainloop()


if __name__ == "__main__":
    main()