"""p9: ¿bloquea la interfaz? Un hilo «UI» que duerme 5 ms y mide su retraso mientras el pipeline p7 corre
(a) en un hilo del mismo proceso (como TaskRunner) o (b) en un proceso trabajador (multiprocessing spawn).
Mide también el coste de devolver la vista previa (ids 1404×540 uint16 + capas por celda) por una tubería.
Uso: python3 -I p9_worker_ui.py thread|process SCALE OUTDIR"""
import io, contextlib, multiprocessing as mp, os, resource, runpy, sys, threading, time
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PROTO = os.path.join(HERE, "p7_pipeline_v2.py")


def run_p7(scale, out):
    sys.argv = [PROTO, "5616", "2160", "60000", "11", out, "--install", "/home/user/corpus/vanilla", "--scale", str(scale), "--river-q", "0.75"]
    with contextlib.redirect_stdout(io.StringIO()):
        runpy.run_path(PROTO, run_name="__main__")


def worker(conn, scale, out):
    t0 = time.perf_counter()
    run_p7(scale, out)
    t1 = time.perf_counter()
    ids = np.zeros((540, 1404), np.uint16); cells = np.zeros((60000, 8), np.float32)
    conn.send_bytes(ids.tobytes()); conn.send_bytes(cells.tobytes())
    conn.send((t1 - t0, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024))
    conn.close()


if __name__ == "__main__":
    mode, scale, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    lat = []; done = threading.Event()

    def ui():
        while not done.is_set():
            t = time.perf_counter(); time.sleep(0.005); lat.append(time.perf_counter() - t - 0.005)
    tu = threading.Thread(target=ui); tu.start(); t0 = time.perf_counter()
    info = {}
    if mode == "thread":
        th = threading.Thread(target=run_p7, args=(scale, out)); th.start(); th.join()
    else:
        ctx = mp.get_context("spawn")
        a, b = ctx.Pipe()
        ts = time.perf_counter()
        p = ctx.Process(target=worker, args=(b, scale, out)); p.start()
        t_ipc = None
        ids = a.recv_bytes(); tr = time.perf_counter(); cells = a.recv_bytes(); work, child_rss = a.recv()
        p.join()
        info = {"child_work_s": round(work, 2), "child_rss_MiB": round(child_rss, 1), "spawn_plus_ipc_overhead_s": round(time.perf_counter() - ts - work, 2)}
    done.set(); tu.join()
    a_ = np.array(lat) * 1000
    print(mode, scale, {"wall_s": round(time.perf_counter() - t0, 2), "ui_overshoot_ms_median": round(float(np.median(a_)), 2),
                        "p99": round(float(np.percentile(a_, 99)), 1), "max": round(float(a_.max()), 1), "gt50": int((a_ > 50).sum()), "gt100": int((a_ > 100).sum()),
                        "parent_rss_MiB": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1), **info})
