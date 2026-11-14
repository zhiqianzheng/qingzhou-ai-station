"""Live, non-blocking capability report for one named client API key."""
import threading
import tkinter as tk
from tkinter import ttk
import backend as b
from capability_tester import BASIC, EXTENDED, report_text

class CapabilityWindow:
    def __init__(self,owner,entry,auto_start=True):
        self.owner=owner;self.entry=entry;self.running=False;self.cancel=threading.Event();self.close_requested=False
        self.report=b.key_test_report(entry['id']);self.rows={}
        self.win=tk.Toplevel(owner.root);self.win.title('API Key 一键测试 · '+entry['name'])
        self.win.geometry('1000x740');self.win.minsize(850,650)
        self.win.protocol('WM_DELETE_WINDOW',self.close)
        frame=ttk.Frame(self.win,padding=18);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='使用者：'+entry['name']+'  ·  Key 指纹：'+entry['id'],font=('Sans',13,'bold')).pack(anchor='w')
        controls=ttk.Frame(frame);controls.pack(fill='x',pady=10)
        ttk.Label(controls,text='测试模型：').pack(side='left')
        self.model=tk.StringVar(value=owner.model.get().strip())
        self.model_box=ttk.Combobox(controls,textvariable=self.model,width=28);self.model_box.pack(side='left')
        ttk.Label(controls,text='  能力请求路径：').pack(side='left')
        self.target=tk.StringVar(value='本机')
        self.target_box=ttk.Combobox(controls,textvariable=self.target,values=['本机','公网'],state='readonly',width=12)
        self.target_box.pack(side='left')
        ttk.Label(frame,text='基础测试会发起真实生成请求并消耗少量额度。全部测试还会调用联网、代码执行、图片和音频等接口，可能额外计费。',wraplength=930).pack(anchor='w')
        actions=ttk.Frame(frame);actions.pack(fill='x',pady=10)
        self.basic_button=ttk.Button(actions,text='基础测试',command=lambda:self.start(False));self.basic_button.pack(side='left')
        self.all_button=ttk.Button(actions,text='全部测试（可能额外计费）',command=lambda:self.start(True));self.all_button.pack(side='left',padx=6)
        self.cancel_button=ttk.Button(actions,text='停止测试',command=self.stop);self.cancel_button.pack(side='left')
        self.copy_button=ttk.Button(actions,text='复制测试报告',command=self.copy_report);self.copy_button.pack(side='right')
        self.status=tk.StringVar(value='准备测试。结果只适用于本次 Key、模型和接口，不代表所有模型或所有能力。')
        ttk.Label(frame,textvariable=self.status,wraplength=930,foreground='#346878').pack(anchor='w',pady=(0,8))
        area=ttk.Frame(frame);area.pack(fill='both',expand=True)
        self.table=ttk.Treeview(area,columns=('name','status','time','detail'),show='headings',selectmode='browse')
        for key,label,width in [('name','检测项目',180),('status','结果',80),('time','耗时',70),('detail','验证依据 / 原因',520)]:
            self.table.heading(key,text=label);self.table.column(key,width=width,minwidth=50)
        scroll=ttk.Scrollbar(area,orient='vertical',command=self.table.yview);self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');self.table.pack(fill='both',expand=True)
        self.table.bind('<<TreeviewSelect>>',lambda _:self.show_detail())
        self.detail=tk.Text(frame,height=5,wrap='word',font=('Sans',10),padx=10,pady=10,state='disabled');self.detail.pack(fill='x',pady=(10,0))
        self.table.tag_configure('通过',foreground='#16734b');self.table.tag_configure('失败',foreground='#a02626')
        self.table.tag_configure('不支持',foreground='#8c5a13');self.table.tag_configure('未验证',foreground='#705b85')
        if self.report:
            self.model.set(self.report['model']);self.model_box.configure(values=self.report.get('models',[]))
            for row in self.report['results']:self.update(row)
            self.status.set('显示上次测试结果；点击按钮可重新实测。')
        if auto_start:
            self.model.set(owner.model.get().strip());self.win.after(100,lambda:self.start(False))
    def post(self,fn):
        try:self.win.after(0,fn)
        except (tk.TclError,RuntimeError):self.cancel.set()
    def start(self,extended):
        if self.running:return
        if self.owner.busy:self.status.set('请先等待主窗口当前操作完成，再开始测试。');return
        model=self.model.get().strip()
        if not model:self.status.set('请填写要测试的模型。');return
        target='public' if self.target.get()=='公网' else 'local'
        self.running=True;self.owner.busy=True;self.cancel=threading.Event();self.report=None;self.rows={}
        self.table.delete(*self.table.get_children())
        self.basic_button.configure(state='disabled');self.all_button.configure(state='disabled');self.copy_button.configure(state='disabled')
        self.model_box.configure(state='disabled');self.target_box.configure(state='disabled')
        self.status.set('正在用选中 Key 实际测试，结果将逐项更新。')
        for id,name in [('auth','连接 / 鉴权 / 模型列表'),('public','公网地址连通性'),('model','当前模型可见性')]+BASIC+EXTENDED:
            self.update({'id':id,'name':name,'status':'待测试','detail':'等待检测。','seconds':0,'http_status':None})
        def worker():
            try:
                report=b.test_key_capabilities(self.entry['id'],model,extended,target,
                      on_update=lambda row:self.post(lambda r=row:self.update(r)),cancel=self.cancel)
                self.post(lambda:self.finish(report,None))
            except Exception as e:
                # Backend validation errors contain no provider response body or key.
                message=str(e) if isinstance(e,ValueError) else '测试遇到异常，未能完成。请确认服务运行后重试。'
                self.post(lambda:self.finish(None,message))
        threading.Thread(target=worker,daemon=True).start()
    def update(self,row):
        self.rows[row['id']]=row
        values=(row['name'],row['status'],f'{row["seconds"]:.2f}s',row['detail'])
        if self.table.exists(row['id']):self.table.item(row['id'],values=values,tags=(row['status'],))
        else:self.table.insert('','end',iid=row['id'],values=values,tags=(row['status'],))
        if row['status']=='测试中':self.status.set('正在测试：'+row['name']);self.table.see(row['id'])
        if row['id'] in self.table.selection():self.show_detail()
    def finish(self,report,error):
        self.running=False;self.owner.busy=False;self.report=report
        for row in list(self.rows.values()):
            if row['status'] in ('待测试','测试中'):
                self.update(dict(row,status='已取消' if self.cancel.is_set() else '未验证',detail=error or '本次未完成该项目。'))
        self.basic_button.configure(state='normal');self.all_button.configure(state='normal')
        self.model_box.configure(state='normal');self.target_box.configure(state='readonly')
        self.copy_button.configure(state='normal' if report else 'disabled')
        if report:
            passed=sum(r['status']=='通过' for r in report['results'])
            self.model_box.configure(values=report.get('models',[]))
            self.status.set(f'测试结束：{passed} 项通过。请查看各项结果；不支持和未验证是不同结论。'+report.get('save_warning',''))
        else:self.status.set(error or '测试未完成。')
        if self.close_requested:self.win.destroy()
    def stop(self):
        if self.running:self.cancel.set();self.status.set('正在停止；当前请求结束或超时后不再继续。已发送的请求可能仍消耗额度。')
    def close(self):
        if self.running:self.close_requested=True;self.stop()
        else:self.win.destroy()
    def copy_report(self):
        if self.report:self.owner.copy(report_text(self.report));self.status.set('测试报告已复制，不包含 API Key。')
    def show_detail(self):
        selected=self.table.selection()
        if not selected:return
        row=self.rows[selected[0]]
        text=f'{row["name"]} · {row["status"]}\n{row["detail"]}\n耗时：{row["seconds"]:.2f} 秒'
        if row.get('http_status'):text+=f'  HTTP：{row["http_status"]}'
        self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.insert('1.0',text);self.detail.configure(state='disabled')
