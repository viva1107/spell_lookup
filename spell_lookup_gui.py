#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NPCSpellLookup GUI (Windows)
图形界面封装，核心查询逻辑在 spell_lookup.py
"""
import os, re, sys, queue, threading, asyncio
import tkinter as tk
from tkinter import ttk, scrolledtext
import webbrowser

import spell_lookup as core

# 禁用命令行进度条动画（GUI 不需要）
core.print_progress = lambda *a, **k: None

ANSI_RE  = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
OSC8_RE  = re.compile(r'\x1b\]8;;([^\x1b\x07]+)\x1b\\(.*?)\x1b\]8;;\x1b\\')


class QueueWriter:
    """把 print 输出转进队列，供 GUI 线程消费。"""
    def __init__(self, q):
        self.q = q
    def write(self, s):
        self.q.put(s)
    def flush(self):
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"NPCSpellLookup  v{core.__version__}  (Made by QQ:646638084)")
        self.geometry("900x620")
        self.minsize(700, 450)
        self.q = queue.Queue()
        self.buf = ""
        self.link_n = 0
        self.searching = False
        self._build()
        self.after(80, self._poll)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI ──────────────────────────────────────────────
    def _build(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)

        ttk.Label(top, text="法术ID 或 精确法术名：").pack(side=tk.LEFT)
        self.entry = ttk.Entry(top, width=30, font=("Consolas", 11))
        self.entry.pack(side=tk.LEFT, padx=6)
        self.entry.bind("<Return>", lambda e: self.start_search())
        self.entry.focus_set()

        self.btn = ttk.Button(top, text="查询", command=self.start_search)
        self.btn.pack(side=tk.LEFT)
        self.clear_btn = ttk.Button(top, text="清空", command=self.clear_output)
        self.clear_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.status = ttk.Label(top, text="就绪", foreground="#888")
        self.status.pack(side=tk.LEFT, padx=12)

        self.out = scrolledtext.ScrolledText(self, wrap=tk.WORD,
                                             font=("Consolas", 10))
        self.out.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.out.tag_config("link", foreground="#4ea1f3", underline=True,
                            font=("Consolas", 10, "underline"))
        self.out.configure(state=tk.DISABLED)

        self._write(f"支持以下查询方式（回车确认）：\n"
                    f"  法术ID      如 133\n"
                    f"  精确法术名  如 Fireball\n"
                    f"  npc <DisplayID>    按外观ID查 NPC 模型/贴图\n"
                    f"  npcid <NPCID>      按生物ID查 NPC 模型/贴图\n"
                    f"数据来自 wago.tools / Wowhead。\n{'─' * 60}\n")

    def _insert(self, text):
        self.out.configure(state=tk.NORMAL)
        # OSC8 超链接 → 可点击文本
        pos = 0
        for m in OSC8_RE.finditer(text):
            if m.start() > pos:
                self._plain(text[pos:m.start()])
            url, label = m.group(1), m.group(2)
            tag = f"lnk{self.link_n}"; self.link_n += 1
            self.out.insert(tk.END, label, (tag,))
            self.out.tag_bind(tag, "<Button-1>",
                              lambda e, u=url: webbrowser.open(u))
            pos = m.end()
        if pos < len(text):
            self._plain(text[pos:])
        self.out.see(tk.END)
        self.out.configure(state=tk.DISABLED)

    def _plain(self, text):
        self.out.insert(tk.END, ANSI_RE.sub("", text))

    def clear_output(self):
        """清空查询记录。"""
        self.buf = ""
        self.out.configure(state=tk.NORMAL)
        self.out.delete("1.0", tk.END)
        self.out.configure(state=tk.DISABLED)

    # ── 查询线程 ────────────────────────────────────────
    def start_search(self):
        if self.searching:
            return
        query = self.entry.get().strip()
        if not query:
            return
        self.searching = True
        self.btn.configure(state=tk.DISABLED)
        self.status.configure(text=f"正在查询 {query} ...")
        self._write(f"\n>>> {query}\n")
        threading.Thread(target=self._worker, args=(query,),
                         daemon=True).start()

    def _worker(self, query):
        old = sys.stdout
        sys.stdout = QueueWriter(self.q)
        try:
            asyncio.run(core.search_and_process(query))
        except Exception as e:
            print(f"\n查询出错: {type(e).__name__}: {e}")
        finally:
            sys.stdout = old
            self.q.put(None)          # 结束哨兵

    # ── 轮询队列 ────────────────────────────────────────
    def _poll(self):
        try:
            while True:
                item = self.q.get_nowait()
                if item is None:                       # 查询结束
                    self._flush(final=True)
                    self.searching = False
                    self.btn.configure(state=tk.NORMAL)
                    self.status.configure(text="就绪")
                    continue
                self.buf += item
                self._flush()
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _flush(self, final=False):
        while True:
            i = self.buf.find("\n")
            if i < 0:
                break
            line, self.buf = self.buf[:i + 1], self.buf[i + 1:]
            self._insert(line)
        if final and self.buf:
            self._insert(self.buf)
            self.buf = ""

    def _write(self, text):
        self.out.configure(state=tk.NORMAL)
        self.out.insert(tk.END, text)
        self.out.see(tk.END)
        self.out.configure(state=tk.DISABLED)

    def _on_close(self):
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
