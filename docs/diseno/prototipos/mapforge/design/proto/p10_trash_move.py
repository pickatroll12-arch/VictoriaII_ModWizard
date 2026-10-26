"""p10: coste de mover a la papelera (os.replace + fsync de directorios) los archivos del mod bajo las carpetas que
el taller reemplaza (C1). Simula el caso VSM: 2 705 historias de provincia, 358 de POPs, 265 OOB, 5 guerras y
4 diplomacias (cuentas medidas con find en el mod), con archivos de 1 KB en la carpeta de trabajo.
Uso: python3 -I p10_trash_move.py DIR"""
import os, sys, time, shutil
root = sys.argv[1]; shutil.rmtree(root, ignore_errors=True)
counts = {"history/provinces/europe": 2705, "history/pops/1836.1.1": 358, "history/units": 265, "history/wars": 5, "history/diplomacy": 4}
for d, n in counts.items():
    os.makedirs(os.path.join(root, "mod", d))
    for i in range(n):
        open(os.path.join(root, "mod", d, f"{i} - x.txt"), "wb").write(b"x" * 1024)
t = time.perf_counter(); dirs = set()
for d in counts:
    src = os.path.join(root, "mod", d); dst = os.path.join(root, "mod", ".vic2studio", "trash", "tx1", d)
    os.makedirs(dst, exist_ok=True)
    for f in os.listdir(src):
        os.replace(os.path.join(src, f), os.path.join(dst, f))
    dirs |= {src, dst}
for d in dirs:
    fd = os.open(d, os.O_RDONLY); os.fsync(fd); os.close(fd)
print("moved", sum(counts.values()), "files in %.3f s" % (time.perf_counter() - t))
shutil.rmtree(root)
