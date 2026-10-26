# v12b: which pipeline phase holds the GIL (stall timestamps vs phase intervals via sys.setprofile on phase.__enter__)
import sys,threading,time,runpy,io,contextlib,os,json
W,H=sys.argv[1],sys.argv[2]
proto=os.path.abspath(os.path.join(os.path.dirname(__file__),'..','..','design','proto','p1_pipeline.py'))
out=os.path.abspath(sys.argv[3])
stalls=[]; done=threading.Event(); marks=[]
def ui():
    while not done.is_set():
        t=time.perf_counter(); time.sleep(0.005); d=time.perf_counter()-t-0.005
        if d>0.08: stalls.append((t,d))
def prof(frame,event,arg):
    if event=='call' and frame.f_code.co_name=='__enter__' and 'name' in frame.f_locals.get('self',{}).__dict__ if hasattr(frame.f_locals.get('self',None),'__dict__') else False:
        marks.append((time.perf_counter(),frame.f_locals['self'].name))
def work():
    sys.argv=[proto,W,H,'60000','11',out,'--terrain-txt','/home/user/corpus/vanilla/map/terrain.txt']
    sys.setprofile(prof)
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        runpy.run_path(proto,run_name='__main__')
    sys.setprofile(None); done.set()
tu=threading.Thread(target=ui); tu.start(); work(); tu.join()
for t,d in stalls:
    ph=[n for (tm,n) in marks if tm<=t]
    print('stall %.0f ms during %s'%(d*1000, ph[-1] if ph else 'setup/import'))
