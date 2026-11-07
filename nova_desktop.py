# -*- coding: utf-8 -*-
"""
NOVA Desktop 2.0
A cautious Windows dashboard: monitoring, temporary/cache cleanup,
startup/program shortcuts, network rates, and notes.
"""
import os, sys, json, time, shutil, subprocess, tempfile, threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

try:
    import psutil
except ImportError:
    psutil = None

APP_NAME = "NOVA Desktop"
APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "NOVA Desktop"
APP_DIR.mkdir(parents=True, exist_ok=True)
NOTES_FILE = APP_DIR / "notes.json"

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
            # Avoid following symlinks and keep traversal within the selected folder.
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

class NovaApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NOVA Desktop 2.0")
        self.root.geometry("1120x720")
        self.root.minsize(900, 600)
        self.root.configure(bg=BG)
        self.last_net = None
        self.net_time = None
        self.current_page = None
        self._style()
        self._layout()
        self.show_page("overview")
        self.refresh_stats()

    def _style(self):
        style = ttk.Style()
        try: style.theme_use("clam")
        except tk.TclError: pass
        style.configure("Treeview", background=PANEL, foreground=TEXT, fieldbackground=PANEL,
                        rowheight=28, borderwidth=0)
        style.configure("Treeview.Heading", background=PANEL2, foreground=TEXT, relief="flat")
        style.map("Treeview", background=[("selected", "#49377a")], foreground=[("selected", "white")])
        style.configure("TProgressbar", troughcolor=PANEL2, background=PURPLE, bordercolor=PANEL2)

    def _layout(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=24, pady=(18, 10))
        tk.Label(header, text="NOVA", bg=BG, fg=TEXT, font=("Segoe UI", 25, "bold")).pack(side="left")
        tk.Label(header, text="  DESKTOP 2.0", bg=BG, fg=PURPLE, font=("Segoe UI", 10, "bold")).pack(side="left", pady=(10,0))
        self.status = tk.Label(header, text="● جاهز", bg=BG, fg=GREEN, font=("Segoe UI", 10))
        self.status.pack(side="right", pady=12)

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=(4,18))
        nav = tk.Frame(body, bg=PANEL, width=205)
        nav.pack(side="left", fill="y", padx=(0,14))
        nav.pack_propagate(False)
        tk.Label(nav, text="مساحة العمل", bg=PANEL, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(anchor="e", padx=18, pady=(22,12))
        items = [("overview","نظرة عامة"),("monitor","مراقبة النظام"),("cleaner","تنظيف الملفات والكاش"),("memory","الذاكرة RAM"),("programs","البرامج"),("network","الشبكة"),("notes","الملاحظات")]
        for key, label in items:
            tk.Button(nav, text=label, command=lambda k=key: self.show_page(k),
                      bg=PANEL, fg=TEXT, activebackground=PANEL2, activeforeground="white",
                      relief="flat", bd=0, anchor="e", padx=18, pady=12,
                      font=("Segoe UI", 10), cursor="hand2").pack(fill="x", padx=8, pady=2)
        tk.Label(nav, text="NOVA • Built for Windows", bg=PANEL, fg="#716b85",
                 font=("Segoe UI", 8)).pack(side="bottom", pady=16)
        self.content = tk.Frame(body, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

    def clear(self):
        for w in self.content.winfo_children(): w.destroy()

    def heading(self, title, desc=""):
        tk.Label(self.content, text=title, bg=BG, fg=TEXT, font=("Segoe UI", 21, "bold")).pack(anchor="e", pady=(8,2))
        if desc:
            tk.Label(self.content, text=desc, bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="e", pady=(0,14))

    def card(self, parent, title, value, note=""):
        f = tk.Frame(parent, bg=PANEL, padx=18, pady=16)
        tk.Label(f, text=title, bg=PANEL, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="e")
        v = tk.Label(f, text=value, bg=PANEL, fg=TEXT, font=("Segoe UI", 22, "bold"))
        v.pack(anchor="e", pady=(7,2))
        if note: tk.Label(f, text=note, bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="e")
        return f, v

    def show_page(self, page):
        self.current_page = page
        self.clear()
        if page == "overview": self.page_overview()
        elif page == "monitor": self.page_monitor()
        elif page == "cleaner": self.page_cleaner()
        elif page == "memory": self.page_memory()
        elif page == "programs": self.page_programs()
        elif page == "network": self.page_network()
        elif page == "notes": self.page_notes()

    def _stats(self):
        if not psutil: return None
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        return cpu, mem, disk

    def page_overview(self):
        self.heading("نظرة عامة", "ملخص سريع لحالة جهازك")
        if not psutil:
            self._need_psutil(); return
        row = tk.Frame(self.content, bg=BG); row.pack(fill="x", pady=8)
        cpu, mem, disk = self._stats()
        for title, value, note in [
            ("المعالج CPU", f"{cpu:.0f}%", "الاستخدام الحالي"),
            ("الذاكرة RAM", f"{mem.percent:.0f}%", f"{fmt_bytes(mem.used)} مستخدم"),
            ("مساحة قرص النظام", fmt_bytes(disk.free), f"من {fmt_bytes(disk.total)} متاح"),
        ]:
            c,_ = self.card(row,title,value,note); c.pack(side="left", fill="both", expand=True, padx=5)
        box = tk.Frame(self.content, bg=PANEL, padx=20, pady=18); box.pack(fill="x", pady=14)
        tk.Label(box, text="ملاحظات مهمة", bg=PANEL, fg=TEXT, font=("Segoe UI", 13, "bold")).pack(anchor="e")
        tips = [
            "ويندوز يدير الذاكرة RAM تلقائيًا؛ NOVA يعرض أكثر البرامج استهلاكًا ويساعدك على إغلاقها يدويًا.",
            "تنظيف الكاش يزيل ملفات مؤقتة محددة فقط، وقد يعيد بعض البرامج إنشاءها لاحقًا.",
            "درجات الحرارة تعتمد على الحساسات التي يتيحها الجهاز؛ قد لا تظهر كل الحساسات على بعض أجهزة AMD.",
        ]
        for t in tips: tk.Label(box, text="• " + t, bg=PANEL, fg=MUTED, font=("Segoe UI", 10), anchor="e", justify="right").pack(fill="x", pady=5)
        tk.Button(self.content, text="تحديث الآن", command=lambda: self.show_page("overview"),
                  bg=PURPLE, fg="white", relief="flat", padx=18, pady=9).pack(anchor="e", pady=8)

    def page_monitor(self):
        self.heading("مراقبة النظام", "استخدام المعالج والذاكرة والقرص ودرجات الحرارة المتاحة")
        if not psutil: self._need_psutil(); return
        wrap = tk.Frame(self.content, bg=BG); wrap.pack(fill="x")
        self.monitor_labels = {}
        for key, label in [("cpu","CPU"),("ram","RAM"),("disk","Disk"),("temp","Temperature")]:
            c, v = self.card(wrap,label,"—")
            c.pack(side="left", fill="both", expand=True, padx=5, pady=5)
            self.monitor_labels[key] = v
        tk.Label(self.content, text="درجة الحرارة قد لا تكون متاحة من Windows على كل الأجهزة. لا يتم التحكم في المراوح من NOVA.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9), wraplength=760, justify="right").pack(anchor="e", pady=12)
        self.update_monitor()

    def read_temp(self):
        # Windows ACPI thermal zone; many laptops do not expose useful CPU/GPU readings here.
        try:
            cmd = ["powershell", "-NoProfile", "-Command",
                   "(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop | Select-Object -First 1 -ExpandProperty CurrentTemperature)"]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=3, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            raw = out.stdout.strip()
            if out.returncode == 0 and raw.isdigit():
                c = int(raw)/10 - 273.15
                if 0 < c < 120: return f"{c:.0f} °C (ACPI)"
        except Exception: pass
        return "غير متاحة"

    def update_monitor(self):
        if self.current_page != "monitor" or not psutil: return
        cpu, mem, disk = self._stats()
        self.monitor_labels["cpu"].config(text=f"{cpu:.0f}%")
        self.monitor_labels["ram"].config(text=f"{mem.percent:.0f}%")
        self.monitor_labels["disk"].config(text=f"{disk.percent:.0f}%")
        self.monitor_labels["temp"].config(text=self.read_temp())
        self.root.after(2500, self.update_monitor)

    def page_cleaner(self):
        self.heading("تنظيف الملفات والكاش", "فحص مجلدات مؤقتة آمنة نسبيًا قبل الحذف")
        note = "لن نحذف ملفات التنزيلات أو المستندات أو كلمات المرور أو بيانات تسجيل الدخول. أغلق البرامج قبل التنظيف."
        tk.Label(self.content, text=note, bg=BG, fg=ORANGE, font=("Segoe UI", 10), wraplength=760, justify="right").pack(anchor="e", pady=(0,12))
        self.clean_vars = {}
        self.clean_rows = tk.Frame(self.content, bg=BG); self.clean_rows.pack(fill="x")
        self.clean_total = tk.Label(self.content, text="لم يتم الفحص بعد", bg=BG, fg=TEXT, font=("Segoe UI", 12, "bold"))
        self.clean_total.pack(anchor="e", pady=12)
        buttons = tk.Frame(self.content, bg=BG); buttons.pack(anchor="e")
        tk.Button(buttons, text="فحص الكاش", command=self.scan_caches, bg=PURPLE, fg="white", relief="flat", padx=16, pady=9).pack(side="right", padx=4)
        self.delete_btn = tk.Button(buttons, text="حذف المحدد", command=self.delete_caches, bg="#653f75", fg="white", relief="flat", padx=16, pady=9, state="disabled")
        self.delete_btn.pack(side="right", padx=4)
        self.cache_results = []

    def scan_caches(self):
        for w in self.clean_rows.winfo_children(): w.destroy()
        self.cache_results = []
        total = 0
        for name, path in cache_targets():
            thumb = "الصور المصغرة" in name
            size, files = scan_path(path, thumbnail_only=thumb)
            total += size
            var = tk.BooleanVar(value=True)
            row = tk.Frame(self.clean_rows, bg=PANEL, padx=12, pady=10); row.pack(fill="x", pady=3)
            tk.Checkbutton(row, text=f"{name} — {fmt_bytes(size)} ({len(files)} ملف)",
                           variable=var, bg=PANEL, fg=TEXT, selectcolor=PANEL2,
                           activebackground=PANEL, activeforeground=TEXT, font=("Segoe UI", 10)).pack(anchor="e")
            self.cache_results.append((name, files, var, size))
        self.clean_total.config(text=f"الإجمالي القابل للفحص: {fmt_bytes(total)}")
        self.delete_btn.config(state="normal")

    def delete_caches(self):
        selected = [(n, fs, s) for n, fs, v, s in self.cache_results if v.get()]
        if not selected:
            messagebox.showinfo("NOVA", "حدد عنصرًا واحدًا على الأقل."); return
        estimate = sum(s for _,_,s in selected)
        if not messagebox.askyesno("تأكيد الحذف", f"سيحاول NOVA حذف الملفات المحددة فقط.\nالحجم التقريبي: {fmt_bytes(estimate)}\nقد يتم تخطي الملفات المستخدمة. هل تريد المتابعة؟"):
            return
        deleted = skipped = 0
        for name, files, _ in selected:
            for p in files:
                if safe_delete(p): deleted += 1
                else: skipped += 1
        messagebox.showinfo("اكتمل التنظيف", f"تمت معالجة الملفات.\nملفات حُذفت/أزيلت: {deleted}\nملفات تم تخطيها أو تعذر حذفها: {skipped}")
        self.scan_caches()

    def page_memory(self):
        self.heading("إدارة الذاكرة RAM", "اعرف البرامج الأكثر استهلاكًا واتخذ قرار الإغلاق بنفسك")
        if not psutil: self._need_psutil(); return
        mem = psutil.virtual_memory()
        c,_ = self.card(self.content,"استخدام الذاكرة",f"{mem.percent:.0f}%",f"{fmt_bytes(mem.used)} من {fmt_bytes(mem.total)}")
        c.pack(fill="x", pady=5)
        tk.Label(self.content, text="تنبيه: لا يوجد زر سحري وآمن لمسح RAM. ويندوز يحرر الذاكرة عند الحاجة؛ إغلاق برنامج لا تستخدمه هو الطريقة العملية.",
                 bg=BG, fg=ORANGE, font=("Segoe UI", 10), wraplength=760, justify="right").pack(anchor="e", pady=12)
        cols=("name","pid","mem")
        tree=ttk.Treeview(self.content, columns=cols, show="headings", height=12)
        for col, title, width in [("name","البرنامج",400),("pid","PID",100),("mem","استهلاك RAM",180)]:
            tree.heading(col,text=title); tree.column(col,width=width,anchor="center")
        tree.pack(fill="both", expand=True, pady=5)
        processes=[]
        for p in psutil.process_iter(["pid","name","memory_info"]):
            try: processes.append((p.info["memory_info"].rss,p.info["name"] or "Unknown",p.info["pid"]))
            except (psutil.NoSuchProcess,psutil.AccessDenied,AttributeError): pass
        for rss,name,pid in sorted(processes,reverse=True)[:30]:
            tree.insert("", "end", values=(name,pid,fmt_bytes(rss)))
        tk.Button(self.content,text="فتح مدير المهام",command=lambda: subprocess.Popen("taskmgr.exe"),
                  bg=PURPLE,fg="white",relief="flat",padx=16,pady=9).pack(anchor="e",pady=10)

    def page_programs(self):
        self.heading("البرامج", "اختصارات قائمة Start؛ إزالة البرامج تتم من إعدادات Windows")
        tree=ttk.Treeview(self.content,columns=("name","path"),show="headings",height=16)
        tree.heading("name",text="اسم البرنامج"); tree.heading("path",text="مسار الاختصار")
        tree.column("name",width=250); tree.column("path",width=560)
        tree.pack(fill="both",expand=True,pady=5)
        folders=[Path(os.environ.get("APPDATA",""))/"Microsoft/Windows/Start Menu/Programs",
                 Path(os.environ.get("PROGRAMDATA",r"C:\ProgramData"))/"Microsoft/Windows/Start Menu/Programs"]
        for folder in folders:
            if folder.exists():
                for p in folder.rglob("*.lnk"):
                    tree.insert("","end",values=(p.stem,str(p)))
        def open_selected():
            sel=tree.selection()
            if not sel: return
            path=tree.item(sel[0],"values")[1]
            try: os.startfile(path)
            except Exception as e: messagebox.showerror("NOVA",str(e))
        bar=tk.Frame(self.content,bg=BG); bar.pack(anchor="e",pady=8)
        tk.Button(bar,text="تشغيل المحدد",command=open_selected,bg=PURPLE,fg="white",relief="flat",padx=14,pady=8).pack(side="right",padx=4)
        tk.Button(bar,text="إعدادات التطبيقات",command=lambda: os.startfile("ms-settings:appsfeatures"),bg=PANEL2,fg=TEXT,relief="flat",padx=14,pady=8).pack(side="right",padx=4)

    def page_network(self):
        self.heading("مراقبة الشبكة", "سرعة الإرسال والاستقبال الحالية على الجهاز، وليست اختبار سرعة الإنترنت")
        self.net_recv=tk.Label(self.content,text="↓ 0 KB/s",bg=PANEL,fg=GREEN,font=("Segoe UI",24,"bold"),padx=24,pady=22)
        self.net_send=tk.Label(self.content,text="↑ 0 KB/s",bg=PANEL,fg=PURPLE,font=("Segoe UI",24,"bold"),padx=24,pady=22)
        self.net_recv.pack(fill="x",pady=6); self.net_send.pack(fill="x",pady=6)
        self.net_note=tk.Label(self.content,text="يتم تحديث القراءة كل ثانية.",bg=BG,fg=MUTED,font=("Segoe UI",9))
        self.net_note.pack(anchor="e",pady=8)
        self.update_network()

    def update_network(self):
        if self.current_page!="network" or not psutil: return
        now=time.time(); counters=psutil.net_io_counters()
        current=(counters.bytes_recv,counters.bytes_sent)
        if self.last_net is not None:
            dt=max(now-self.net_time,0.01)
            self.net_recv.config(text=f"↓ {fmt_bytes((current[0]-self.last_net[0])/dt)}/s")
            self.net_send.config(text=f"↑ {fmt_bytes((current[1]-self.last_net[1])/dt)}/s")
        self.last_net,self.net_time=current,now
        self.root.after(1000,self.update_network)

    def page_notes(self):
        self.heading("الملاحظات السريعة", "تُحفظ الملاحظات محليًا على جهازك")
        box=tk.Text(self.content,bg=PANEL,fg=TEXT,insertbackground=TEXT,relief="flat",
                    font=("Segoe UI",12),wrap="word",padx=14,pady=14)
        box.pack(fill="both",expand=True,pady=6)
        try:
            if NOTES_FILE.exists():
                data=json.loads(NOTES_FILE.read_text(encoding="utf-8"))
                box.insert("1.0",data.get("text",""))
        except Exception: pass
        def save():
            NOTES_FILE.write_text(json.dumps({"text":box.get("1.0","end-1c")},ensure_ascii=False,indent=2),encoding="utf-8")
            messagebox.showinfo("NOVA","تم حفظ الملاحظات.")
        tk.Button(self.content,text="حفظ",command=save,bg=PURPLE,fg="white",relief="flat",padx=18,pady=9).pack(anchor="e",pady=8)

    def _need_psutil(self):
        tk.Label(self.content,text="مكتبة psutil غير مثبتة. شغّل run_nova.bat لتثبيتها تلقائيًا.",
                 bg=BG,fg=ORANGE,font=("Segoe UI",11)).pack(anchor="e",pady=20)

    def refresh_stats(self):
        if psutil: psutil.cpu_percent(interval=None)
        self.root.after(3000,self.refresh_stats)

def main():
    root=tk.Tk()
    app=NovaApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
