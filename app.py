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
        self.root=root;self.busy=False;self.last_rows=[];self.last_history_signature=None
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
        connect=ttk.Frame(book,padding=18);history=ttk.Frame(book,padding=18);keys=ttk.Frame(book,padding=18)
        book.add(connect,text='连接与服务');book.add(history,text='对话记录');book.add(keys,text='API Key 管理')
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
        ttk.Label(history,text='每把 Key 保留最近 500 次请求 · 全部视图显示最近 500 条 · 图片和音频不记录',wraplength=850).pack(anchor='w',pady=(0,8))
        filter_row=ttk.Frame(history);filter_row.pack(fill='x',pady=(0,10))
        ttk.Label(filter_row,text='查看使用者 / Key：').pack(side='left')
        self.history_filter=tk.StringVar(value='全部 API Key');self.history_choices={'全部 API Key':None}
        self.filter_box=ttk.Combobox(filter_row,textvariable=self.history_filter,state='readonly',width=55)
        self.filter_box.pack(side='left',fill='x',expand=True)
        self.filter_box.bind('<<ComboboxSelected>>',lambda _:self.refresh_history())
        pane=ttk.Panedwindow(history,orient='vertical');pane.pack(fill='both',expand=True)
        upper=ttk.Frame(pane);lower=ttk.Frame(pane);pane.add(upper,weight=1);pane.add(lower,weight=2)
        self.table=ttk.Treeview(upper,columns=('time','person','key','model','status'),show='headings',height=7,selectmode='browse')
        for name,title,width in [('time','时间',145),('person','使用者备注',155),('key','Key 指纹',115),('model','模型',165),('status','状态',95)]:
            self.table.heading(name,text=title);self.table.column(name,width=width,stretch=True)
        scrollbar=ttk.Scrollbar(upper,orient='vertical',command=self.table.yview);self.table.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');self.table.pack(fill='both',expand=True)
        self.table.bind('<<TreeviewSelect>>',lambda _:self.show_detail())
        self.detail=tk.Text(lower,wrap='word',bg='#ffffff',fg='#173347',padx=12,pady=12,font=('Sans',11),height=12,state='disabled')
        scroll=ttk.Scrollbar(lower,orient='vertical',command=self.detail.yview);self.detail.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.detail.pack(fill='both',expand=True,pady=(8,0))
        self.build_key_tab(keys)
        self.refresh();self.poll_history();self.log('欢迎。现有配置已保留。对话记录默认关闭，需要告知使用者后手动开启。')
        if b.tailscale():root.after(500,lambda:self.task(b.public_status))
    def build_key_tab(self,parent):
        self.key_action_in_progress=False;self.pending_key_id=None;self.keys={}
        ttk.Label(parent,text='给每位使用者创建独立的 API Key',font=('Sans',15,'bold')).pack(anchor='w')
        ttk.Label(parent,text='所有 Key 使用同一个中转地址和上游账号额度。备注会显示在对话记录中；启用对话记录后才能保存聊天。',wraplength=850).pack(anchor='w',pady=10)
        row=ttk.Frame(parent);row.pack(fill='x',pady=(0,10))
        for text,fn in [('创建 API Key',self.create_key),('复制 Key + URL',self.copy_key_connection),('修改备注',self.rename_key),('启用 / 停用',self.toggle_key),('删除密钥',self.delete_key),('刷新列表',self.refresh_keys)]:
            ttk.Button(row,text=text,command=fn).pack(side='left',padx=(0,6))
        self.key_table=ttk.Treeview(parent,columns=('name','id','status','created'),show='headings',height=9,selectmode='browse')
        for name,title,width in [('name','使用者备注',240),('id','Key 指纹',150),('status','状态',90),('created','创建 / 导入时间',170)]:
            self.key_table.heading(name,text=title);self.key_table.column(name,width=width)
        self.key_table.pack(fill='both',expand=True,pady=(0,12));self.key_table.bind('<<TreeviewSelect>>',lambda _:self.show_key())
        self.selected_key_value=tk.StringVar();self.field(parent,'选中 API Key',self.selected_key_value,True)
        self.key_status=tk.StringVar(value='先创建密钥并填写使用者备注，再复制给对应的人。现有密钥会自动导入，不会被替换。')
        ttk.Label(parent,textvariable=self.key_status,wraplength=850,foreground='#346878').pack(anchor='w',pady=12)
        ttk.Label(parent,text='创建、启停或删除密钥会自动重启运行中的中转服务，当前连接会断开。已有对话记录会保留。',wraplength=850).pack(anchor='w')
    def refresh_keys(self):
        if not hasattr(self,'key_table'):return
        selected=self.pending_key_id or next(iter(self.key_table.selection()),None);self.pending_key_id=None
        entries=b.key_manager().list();self.keys={e['id']:e for e in entries}
        self.key_table.delete(*self.key_table.get_children())
        for e in entries:
            self.key_table.insert('','end',iid=e['id'],values=(e['name'],e['id'],'启用' if e['enabled'] else '停用',time.strftime('%Y-%m-%d %H:%M',time.localtime(e['created']))))
        if selected and self.key_table.exists(selected):self.key_table.selection_set(selected)
        self.show_key()
    def selected_key(self):
        selected=self.key_table.selection()
        if not selected:self.key_status.set('请先在列表里选择一把密钥。');return None
        return self.keys.get(selected[0])
    def show_key(self):
        selected=self.key_table.selection();entry=self.keys.get(selected[0]) if selected else None
        self.selected_key_value.set(entry.get('secret','') if entry else '')
    def key_task(self,fn):
        if self.busy:return
        self.key_action_in_progress=True;self.key_status.set('正在保存密钥配置…');self.task(fn)
    def create_key(self):
        if self.busy:return
        name=simpledialog.askstring('创建 API Key','使用者备注（例如：张三、测试客户 A）：',parent=self.root)
        if name is None:return
        def create():
            entry=b.create_key(name);self.pending_key_id=entry['id']
            return '密钥已创建并选中。点击「复制 Key + URL」即可把完整连接信息发给对应使用者。'
        self.key_task(create)
    def copy_key_connection(self):
        if self.busy:return
        entry=self.selected_key()
        if not entry:return
        model=self.model.get().strip()
        def prepare():
            text=b.share_connection(entry['id'],model)
            self.root.after(0,lambda:self.copy(text))
            return '已复制使用者备注、API Key、公网 URL、模型名和使用告知，可以直接发给朋友。'
        self.key_task(prepare)
    def rename_key(self):
        if self.busy:return
        entry=self.selected_key()
        if not entry:return
        name=simpledialog.askstring('修改使用者备注','使用者备注：',initialvalue=entry['name'],parent=self.root)
        if name is None:return
        self.key_task(lambda:(b.key_manager().update(entry['id'],name=name),'使用者备注已更新。')[1])
    def toggle_key(self):
        if self.busy:return
        entry=self.selected_key()
        if not entry:return
        enable=not entry['enabled']
        self.key_task(lambda:(b.key_manager().update(entry['id'],enabled=enable),'密钥已'+('启用' if enable else '停用')+'，配置已保存；运行中的服务已自动重启。')[1])
    def delete_key(self):
        if self.busy:return
        entry=self.selected_key()
        if not entry:return
        if messagebox.askyesno('删除密钥',f'删除「{entry["name"]}」的 API Key？该 Key 将失效，已有对话记录会保留。',parent=self.root):
            self.key_task(lambda:(b.key_manager().update(entry['id'],delete=True),'密钥已删除，已有对话记录保留。')[1])
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
        self.refresh_keys()
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
        if self.key_action_in_progress:self.key_status.set(str(result));self.key_action_in_progress=False
        self.poll_history(schedule=False,force=True)
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
            labels=b.key_labels()
            current=self.history_choices.get(self.history_filter.get())
            ids=set(labels)|set(b.store().key_ids())
            choices={'全部 API Key':None}
            for id in sorted(ids):choices[f'{labels.get(id,"未备注")} · {id}']=id
            selected_label=next((name for name,id in choices.items() if id==current),'全部 API Key')
            self.history_choices=choices;self.filter_box.configure(values=list(choices));self.history_filter.set(selected_label)
            current=choices[selected_label]
            rows=b.store().recent(current)
            signature=(current,tuple(sorted(labels.items())))
            if force or rows!=self.last_rows or signature!=self.last_history_signature:
                selected=self.table.selection();self.table.delete(*self.table.get_children())
                for r in rows:
                    self.table.insert('','end',iid=str(r['id']),values=(time.strftime('%m-%d %H:%M:%S',time.localtime(r['created'])),labels.get(r['key_id'],'未备注'),r['key_id'],r['model'],r['status']))
                if selected and self.table.exists(selected[0]):self.table.selection_set(selected[0])
                self.last_rows=rows;self.last_history_signature=signature;self.show_detail()
            self.record_status.set('● 对话记录已开启' if b.store().options().get('enabled') else '○ 对话记录已关闭')
        except Exception:pass
        if schedule:self.root.after(1500,self.poll_history)
    def show_detail(self):
        selected=self.table.selection();row=b.store().detail(int(selected[0])) if selected else None
        text='选择一条请求，查看使用者发送的文字和 AI 回复。'
        if row:
            try:messages=json.loads(row['request'])
            except ValueError:messages=[{'role':'请求','content':row['request']}]
            name=b.key_labels().get(row['key_id'],'未备注')
            text=f'使用者：{name}  ·  Key 指纹：{row["key_id"]}\n\n发送的消息（客户端可能包含历史上下文）：\n\n'
            text+='\n\n'.join(f'[{m["role"]}]\n{m["content"]}' for m in messages)
            text+='\n\n──────── AI 回复 ────────\n\n'+(row['response'] or '等待回复或没有可提取的文字内容。')
            if row['truncated']:text+='\n\n[内容超过记录上限，已截断]'
        self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.insert('1.0',text);self.detail.configure(state='disabled')

def main():
    root=tk.Tk();App(root);root.mainloop()

if __name__=='__main__':main()
