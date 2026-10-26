# v12: GIL stalls seen by a "UI" thread while the p1 pipeline runs in a worker thread (like TaskRunner)
import sys,threading,time,runpy,io,contextlib,os,numpy as np
W,H=sys.argv[1],sys.argv[2]
proto=os.path.abspath(os.path.join(os.path.dirname(__file__),'..','..','design','proto','p1_pipeline.py'))
out=os.path.abspath(sys.argv[3])
lat=[]; done=threading.Event()
def ui():
    while not done.is_set():
        t=time.perf_counter(); time.sleep(0.005); lat.append(time.perf_counter()-t-0.005)
def work():
    sys.argv=[proto,W,H,'60000','11',out,'--terrain-txt','/home/user/corpus/vanilla/map/terrain.txt']
    with contextlib.redirect_stdout(io.StringIO()):
        runpy.run_path(proto,run_name='__main__')
    done.set()
tu=threading.Thread(target=ui); tu.start(); t0=time.perf_counter(); work(); tu.join()
a=np.array(lat)*1000
print('wall %.1f s; UI tick overshoot ms: median %.1f p99 %.1f max %.1f; ticks>50ms %d, >100ms %d, >250ms %d'%(time.perf_counter()-t0,np.median(a),np.percentile(a,99),a.max(),(a>50).sum(),(a>100).sum(),(a>250).sum()))
