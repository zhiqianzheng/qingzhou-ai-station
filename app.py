#!/usr/bin/env python3
"""Qingzhou AI Station desktop entry point."""
import json
import re
import sys
import threading
import time
import webbrowser
from pathlib import Path

# PyInstaller uses the same entry point for the detached recording service.
if len(sys.argv)>1 and sys.argv[1]=='--recorder':
    from recorder import main
    main(sys.argv[2]);sys.exit(0)

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import backend as b
from recorder import NOTICE

class App:
    def __init__(self,root):
        self.root=root;self.busy=False;self.last_rows=[]
        root.title('轻舟 AI 中转站 · Qingzhou');root.geometry('990x820');root.minsize(860,740)
        self.icon=tk.PhotoImage(file=str(b.BUNDLE/'assets/icon.png'));root.iconphoto(True,self.icon)
        style=ttk.Style();style.theme_use('clam')
        style.configure('TFrame',background='#f2f6fa');style.configure('TLabel',background='#f2f6fa',font=('Sans',11))
        style.configure('Title.TLabel',font=('Sans',24,'bold'),foreground='#12304a')
        style.configure('TButton',padding=(12,8),font=('Sans',10))
        style.configure('TNotebook.Tab',padding=(22,10),font=('Sans',11))
        shell=ttk.Frame(root,padding=22);shell.pack(fill='both',expand=True)
        head=ttk.Frame(shell);head.pack(fill='x',pady=(0,14))
        self.small=self.icon.subsample(8)
        ttk.Label(head,image=self.small).pack(side='left',padx=(0,12))
        title=ttk.Frame(head);title.pack(side='left')
        ttk.Label(title,text='轻舟 AI 中转站',style='Title.TLabel').pack(anchor='w')
        ttk.Label(title,text='自己的账号 · 清晰的连接 · 本机掌控',foreground='#567080').pack(anchor='w')
        book=ttk.Notebook(shell);book.pack(fill='both',expand=True)
        connect=ttk.Frame(book,padding=18);history=ttk.Frame(book,padding=18)
        book.add(connect,text='连接与服务');book.add(history,text='对话记录')
        self.status=tk.StringVar();self.accounts=tk.StringVar()
        ttk.Label(connect,textvariable=self.status).pack(anchor='w')
        ttk.Label(connect,textvariable=self.accounts,wraplength=850).pack(anchor='w',pady=8)
        row=ttk.Frame(connect);row.pack(fill='x',pady=8)
        for label,fn in [('一键配置 / 启动',b.start),('登录 ChatGPT',b.login),('停止服务',b.stop),('刷新状态',lambda:'状态已刷新')]:
            ttk.Button(row,text=label,command=lambda f=fn:self.task(f)).pack(side='left',padx=(0,8))
        ttk.Label(connect,text='首次使用：启动 → 浏览器授权 → 测试连接。无需在 App 内填写账号密码。',wraplength=850).pack(anchor='w',pady=8)
        self.url=tk.StringVar();self.public=tk.StringVar(value='尚未查询');self.key=tk.StringVar();self.model=tk.StringVar(value='gpt-6.1-sol')
        self.field(connect,'本机 Base URL',self.url)
        self.field(connect,'公网 Base URL',self.public)
        self.field(connect,'API Key',self.key,True)
        self.field(connect,'测试模型',self.model,editable=True)
        row=ttk.Frame(connect);row.pack(fill='x',pady=12)
        for label,fn in [('测试连接',lambda:b.test(self.test_model)),('查看公网',b.public_status),('开启公网',lambda:b.enable_public(self.open_url)),('关闭公网',b.disable_public)]:
            ttk.Button(row,text=label,command=lambda f=fn:self.task(f)).pack(side='left',padx=(0,8))
        ttk.Button(row,text='网络代理',command=self.proxy_dialog).pack(side='left')
        ttk.Label(connect,text='开启公网会安装 / 配置 Tailscale，并引导本人登录授权。关闭窗口后服务继续运行。',wraplength=850).pack(anchor='w',pady=5)
        self.output=tk.Text(connect,height=7,wrap='word',bg='#152b40',fg='#dceef4',relief='flat',padx=12,pady=10,font=('Sans',10))
        self.output.pack(fill='both',expand=True,pady=(10,0));self.output.configure(state='disabled')
        self.record_status=tk.StringVar()
        ttk.Label(history,textvariable=self.record_status,font=('Sans',13,'bold')).pack(anchor='w')
        ttk.Label(history,text=NOTICE,wraplength=850,foreground='#705319').pack(anchor='w',pady=10)
        row=ttk.Frame(history);row.pack(fill='x',pady=(0,10))
        ttk.Button(row,text='开启记录（已告知使用者）',command=self.enable_recording).pack(side='left')
        ttk.Button(row,text='关闭记录',command=lambda:self.task(lambda:b.recording(False))).pack(side='left',padx=6)
        ttk.Button(row,text='复制使用告知',command=lambda:self.copy(NOTICE)).pack(side='left')
        ttk.Button(row,text='清空记录',command=self.clear_history).pack(side='right')
        ttk.Button(row,text='刷新记录',command=self.refresh_history).pack(side='right',padx=6)
        ttk.Label(history,text='最近 500 次请求 · 仅保存在本机 · 共用同一个 Key 无法区分具体使用者 · 图片和音频不记录',wraplength=850).pack(anchor='w',pady=(0,10))
        pane=ttk.Panedwindow(history,orient='vertical');pane.pack(fill='both',expand=True)
        upper=ttk.Frame(pane);lower=ttk.Frame(pane);pane.add(upper,weight=1);pane.add(lower,weight=2)
        self.table=ttk.Treeview(upper,columns=('time','key','model','status'),show='headings',height=7,selectmode='browse')
        for name,title,width in [('time','时间',165),('key','Key 指纹',115),('model','模型',210),('status','状态',110)]:
            self.table.heading(name,text=title);self.table.column(name,width=width,stretch=True)
        scrollbar=ttk.Scrollbar(upper,orient='vertical',command=self.table.yview);self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');self.table.pack(fill='both',expand=True)
        self.table.bind('<<TreeviewSelect>>',lambda _:self.show_detail())
        self.detail=tk.Text(lower,wrap='word',bg='#ffffff',fg='#173347',padx=12,pady=12,font=('Sans',11),height=12,state='disabled')
        scroll=ttk.Scrollbar(lower,orient='vertical',command=self.detail.yview);self.detail.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.detail.pack(fill='both',expand=True,pady=(8,0))
        self.refresh();self.poll_history();self.log('欢迎。现有配置已保留。对话记录默认关闭，需要告知使用者后手动开启。')
        if b.tailscale():root.after(500,lambda:self.task(b.public_status))
    def field(self,parent,label,var,secret=False,editable=False):
        row=ttk.Frame(parent);row.pack(fill='x',pady=5)
        ttk.Label(row,text=label,width=16).pack(side='left')
        entry=ttk.Entry(row,textvariable=var,show='•' if secret else '',font=('Sans',11));entry.pack(side='left',fill='x',expand=True)
        if not editable:entry.configure(state='readonly')
        if secret:ttk.Button(row,text='显示',command=lambda:entry.configure(show='' if entry.cget('show') else '•')).pack(side='left',padx=5)
        ttk.Button(row,text='复制',command=lambda:self.copy(var.get())).pack(side='left',padx=5)
    def copy(self,value):self.root.clipboard_clear();self.root.clipboard_append(value)
    def open_url(self,url):self.root.after(0,lambda:webbrowser.open(url))
    def log(self,text):
        self.output.configure(state='normal');self.output.insert('end',str(text)+'\n');self.output.see('end');self.output.configure(state='disabled')
    def refresh(self):
        port,key=b.settings();self.url.set(f'http://127.0.0.1:{port}/v1');self.key.set(key)
        self.status.set('● 中转服务运行中' if b.active() else '○ 中转服务未启动')
        self.accounts.set('账号：'+b.accounts())
        self.record_status.set('● 对话记录已开启' if b.store().options().get('enabled') else '○ 对话记录已关闭')
    def task(self,fn):
        if self.busy:return
        self.busy=True;self.test_model=self.model.get().strip();self.log('正在处理…如出现浏览器或系统授权窗口，请按提示完成。')
        def worker():
            try:result=fn() or '操作完成'
            except Exception as e:result='未完成：'+str(e)
            self.root.after(0,lambda:self.done(result))
        threading.Thread(target=worker,daemon=True).start()
    def done(self,result):
        self.busy=False;self.refresh();self.log(result)
        match=re.search(r'https://[a-zA-Z0-9.:-]+\.ts\.net',str(result))
        if match:self.public.set(match[0]+'/v1')
    def proxy_dialog(self):
        if self.busy:return
        value=simpledialog.askstring('网络代理','代理地址，例如 http://127.0.0.1:7897；留空表示直连。',parent=self.root)
        if value is None:return
        value=value.strip()
        if value and not re.fullmatch(r'(https?|socks5h?)://[^\s"\']+',value):
            messagebox.showerror('地址错误','请填写 http://、https:// 或 socks5:// 开头的地址。');return
        self.task(lambda:b.set_proxy(value))
    def enable_recording(self):
        if self.busy:return
        if messagebox.askyesno('开启对话记录',NOTICE+'\n\n你已向使用者说明并取得同意了吗？',parent=self.root):
            self.task(lambda:b.recording(True))
    def clear_history(self):
        if messagebox.askyesno('清空记录','永久删除本机保存的全部对话记录？',parent=self.root):
            b.store().clear();self.last_rows=[];self.poll_history(schedule=False);self.show_detail()
    def refresh_history(self):
        self.poll_history(schedule=False,force=True)
        if not self.table.selection() and self.table.get_children():
            latest=self.table.get_children()[0]
            self.table.selection_set(latest);self.table.see(latest)
        self.show_detail()
    def poll_history(self,schedule=True,force=False):
        try:
            rows=b.store().recent()
            if force or rows!=self.last_rows:
                selected=self.table.selection();self.table.delete(*self.table.get_children())
                for r in rows:
                    self.table.insert('','end',iid=str(r['id']),values=(time.strftime('%m-%d %H:%M:%S',time.localtime(r['created'])),r['key_id'],r['model'],r['status']))
                if selected and self.table.exists(selected[0]):self.table.selection_set(selected[0])
                self.last_rows=rows;self.show_detail()
            self.record_status.set('● 对话记录已开启' if b.store().options().get('enabled') else '○ 对话记录已关闭')
        except Exception:pass
        if schedule:self.root.after(1500,self.poll_history)
    def show_detail(self):
        selected=self.table.selection();row=b.store().detail(int(selected[0])) if selected else None
        text='选择一条请求，查看使用者发送的文字和 AI 回复。'
        if row:
            try:messages=json.loads(row['request'])
            except ValueError:messages=[{'role':'请求','content':row['request']}]
            text='发送的消息（客户端可能包含历史上下文）：\n\n'
            text+='\n\n'.join(f'[{m["role"]}]\n{m["content"]}' for m in messages)
            text+='\n\n──────── AI 回复 ────────\n\n'+(row['response'] or '等待回复或没有可提取的文字内容。')
            if row['truncated']:text+='\n\n[内容超过记录上限，已截断]'
        self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.insert('1.0',text);self.detail.configure(state='disabled')

def main():
    root=tk.Tk();App(root);root.mainloop()

if __name__=='__main__':main()
