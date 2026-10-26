"""p1b: ¿la vista previa (W/4) predice el render final? Compara la partición celda→provincia de las dos
ejecuciones de p1 con la misma semilla (contingencia: fracción de celdas cuya provincia de la vista previa
coincide con la mayoritaria en el final) y los píxeles del ráster submuestreado.
Uso: python3 -I p1b_preview_vs_final.py OUT_PREVIEW OUT_FINAL"""
import sys
import numpy as np
a = np.load(sys.argv[1] + "/cell_prov.npy"); b = np.load(sys.argv[2] + "/cell_prov.npy")
k = a.astype(np.int64) * (b.max() + 1) + b
u, c = np.unique(k, return_counts=True)
pa, pb = np.divmod(u, b.max() + 1)
o = np.lexsort((-c, pa)); f = np.ones(o.size, bool); f[1:] = pa[o][1:] != pa[o][:-1]
agree = c[o][f].sum() / a.size
print("cells_same_partition_frac", round(float(agree), 4))
ia = np.load(sys.argv[1] + "/ids_small.npy"); ib = np.load(sys.argv[2] + "/ids_small.npy")
m = dict(zip(pa[o][f].tolist(), pb[o][f].tolist()))
# píxel a píxel: provincia de la vista previa traducida a la del final
lut = np.zeros(int(ia.max()) + 1, np.int64)
# mapa de ids de la vista previa → final por mayoría de píxeles
kk = ia.astype(np.int64).ravel() * (int(ib.max()) + 1) + ib.ravel()
u2, c2 = np.unique(kk, return_counts=True); qa, qb = np.divmod(u2, int(ib.max()) + 1)
o2 = np.lexsort((-c2, qa)); f2 = np.ones(o2.size, bool); f2[1:] = qa[o2][1:] != qa[o2][:-1]
print("pixels_same_province_frac", round(float(c2[o2][f2].sum() / ia.size), 4))
print("provinces_preview_final", int(ia.max()), int(ib.max()))
