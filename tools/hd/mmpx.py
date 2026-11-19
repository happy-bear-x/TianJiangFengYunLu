"""MMPX 像素画放大算法（Python / NumPy 向量化实现）

规则逐条移植自官方 OpenGL ES 实现：
  McGuire & Gagiu, "MMPX Style-Preserving Pixel-Art Magnification", JCGT 2021
  https://casual-effects.com/research/McGuire2021PixelArt/McGuire2021PixelArt-supplement.zip
  code/data-files/MMPX.glc

用途：在 PC 上离线验证"2x MMPX + 收尾缩放"相比现状 nearest 的实际收益，
      决定是否值得把 MMPX 编进引擎 shader。

实现要点：
  - 用 uint32 打包像素（0x00BBGGRR），整像素比较，避免浮点误差
  - 规则按官方顺序依次应用（后面的覆盖前面的），每条规则都是布尔掩码批量赋值
  - 邻域用 np.roll / 切片实现，边界按 clamp 复制
"""
import numpy as np


def _pack(rgb: np.ndarray) -> np.ndarray:
    """(H,W,3) uint8 -> (H,W) uint32  0x00BBGGRR"""
    rgb = rgb.astype(np.uint32)
    return rgb[:, :, 0] | (rgb[:, :, 1] << 8) | (rgb[:, :, 2] << 16)


def _unpack(p: np.ndarray) -> np.ndarray:
    out = np.empty(p.shape + (3,), dtype=np.uint8)
    out[:, :, 0] = (p & 0xFF).astype(np.uint8)
    out[:, :, 1] = ((p >> 8) & 0xFF).astype(np.uint8)
    out[:, :, 2] = ((p >> 16) & 0xFF).astype(np.uint8)
    return out


def _shift(p: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """取 p[x+dx, y+dy]，越界用边缘像素复制（等价 GL 的 clamp）。"""
    h, w = p.shape
    ys = np.clip(np.arange(h) + dy, 0, h - 1)
    xs = np.clip(np.arange(w) + dx, 0, w - 1)
    return p[np.ix_(ys, xs)]


def _luma(p: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """官方 luma：((r+g+b)+1) * (256-alpha)。返回 int64 防溢出。"""
    r = (p & 0xFF).astype(np.int64)
    g = ((p >> 8) & 0xFF).astype(np.int64)
    b = ((p >> 16) & 0xFF).astype(np.int64)
    return (r + g + b + 1) * (256 - alpha.astype(np.int64))


def mmpx2x(img: np.ndarray) -> np.ndarray:
    """2 倍 MMPX。img: (H,W,3) uint8 或 (H,W,4) uint8（alpha 参与 luma）。"""
    if img.ndim != 3 or img.shape[2] not in (3, 4):
        raise ValueError("expect (H,W,3|4)")

    src = _pack(img[:, :, :3])
    h, w = src.shape
    alpha = img[:, :, 3] if img.shape[2] == 4 else np.full((h, w), 255, np.uint8)

    # 3x3 邻域
    A = _shift(src, -1, -1); B = _shift(src, 0, -1); C = _shift(src, 1, -1)
    D = _shift(src, -1,  0); E = src;                F = _shift(src, 1,  0)
    G = _shift(src, -1,  1); H = _shift(src, 0,  1); I = _shift(src, 1,  1)

    # 2 距离与 3 距离邻域
    P = _shift(src, 0, -2); S = _shift(src, 0, 2)
    Q = _shift(src, -2, 0); R = _shift(src, 2, 0)

    al = _shift(alpha, 0, 0)
    Bl = _luma(B, _shift(alpha, 0, -1)); Dl = _luma(D, _shift(alpha, -1, 0))
    El = _luma(E, al)
    Fl = _luma(F, _shift(alpha, 1, 0)); Hl = _luma(H, _shift(alpha, 0, 1))

    # 输出四块，初始都等于 E
    J = E.copy(); K = E.copy(); L = E.copy(); M = E.copy()

    def eq(a, b):
        return a == b

    def all_eq2(Bv, A0, A1):
        return (Bv == A0) & (Bv == A1)

    def all_eq3(Bv, A0, A1, A2):
        return (Bv == A0) & (Bv == A1) & (Bv == A2)

    def all_eq4(Bv, A0, A1, A2, A3):
        return (Bv == A0) & (Bv == A1) & (Bv == A2) & (Bv == A3)

    def any_eq3(Bv, A0, A1, A2):
        return (Bv == A0) | (Bv == A1) | (Bv == A2)

    def none_eq2(Bv, A0, A1):
        return (Bv != A0) & (Bv != A1)

    def none_eq4(Bv, A0, A1, A2, A3):
        return (Bv != A0) & (Bv != A1) & (Bv != A2) & (Bv != A3)

    def assign(mask, target, value):
        # 官方写法 J = D 这类，是整块覆盖
        if isinstance(target, list):
            for t in target:
                t[mask] = value[mask]
        else:
            target[mask] = value[mask]

    # 非恒定邻域才处理（全平的区域直接复制 2x2）
    active = ((A != E) | (B != E) | (C != E) | (D != E)
              | (F != E) | (G != E) | (H != E) | (I != E))

    # ---- 1:1 slope rules ----
    m = ((D == B) & (D != H) & (D != F) & ((El >= Dl) | (E == A))
         & any_eq3(E, A, C, G) & ((El < Dl) | (A != D) | (E != P) | (E != Q)))
    assign(m, J, D)

    m = ((B == F) & (B != D) & (B != H) & ((El >= Bl) | (E == C))
         & any_eq3(E, A, C, I) & ((El < Bl) | (C != B) | (E != P) | (E != R)))
    assign(m, K, B)

    m = ((H == D) & (H != F) & (H != B) & ((El >= Hl) | (E == G))
         & any_eq3(E, A, G, I) & ((El < Hl) | (G != H) | (E != S) | (E != Q)))
    assign(m, L, H)

    m = ((F == H) & (F != B) & (F != D) & ((El >= Fl) | (E == I))
         & any_eq3(E, C, G, I) & ((El < Fl) | (I != H) | (E != R) | (E != S)))
    assign(m, M, F)

    # ---- Intersection rules ----
    m = ((E != F) & all_eq4(E, C, I, D, Q) & all_eq2(F, B, H)
         & (F != _shift(src, 3, 0)))
    assign(m, [K, M], F)

    m = ((E != D) & all_eq4(E, A, G, F, R) & all_eq2(D, B, H)
         & (D != _shift(src, -3, 0)))
    assign(m, [J, L], D)

    m = ((E != H) & all_eq4(E, G, I, B, P) & all_eq2(H, D, F)
         & (H != _shift(src, 0, 3)))
    assign(m, [L, M], H)

    m = ((E != B) & all_eq4(E, A, C, H, S) & all_eq2(B, D, F)
         & (B != _shift(src, 0, -3)))
    assign(m, [J, K], B)

    m = (Bl < El) & all_eq4(E, G, H, I, S) & none_eq4(E, A, D, C, F)
    assign(m, [J, K], B)

    m = (Hl < El) & all_eq4(E, A, B, C, P) & none_eq4(E, D, G, I, F)
    assign(m, [L, M], H)

    m = (Fl < El) & all_eq4(E, A, D, G, Q) & none_eq4(E, B, C, I, H)
    assign(m, [K, M], F)

    m = (Dl < El) & all_eq4(E, C, F, I, R) & none_eq4(E, B, A, G, H)
    assign(m, [J, L], D)

    # ---- 2:1 slope rules ----
    outer = (H != B)
    if outer.any():
        c1 = outer & (H != A) & (H != E) & (H != C)
        m = c1 & all_eq3(H, G, F, R) & none_eq2(H, D, _shift(src, 2, -1))
        assign(m, [L, M], M)          # L = M （把 M 当前值赋给 L）
        m = c1 & all_eq3(H, I, D, Q) & none_eq2(H, F, _shift(src, -2, -1))
        assign(m, [M, L], L)          # M = L

        c2 = outer & (B != I) & (B != G) & (B != E)
        m = c2 & all_eq3(B, A, F, R) & none_eq2(B, D, _shift(src, 2, 1))
        assign(m, [J, K], K)          # J = K
        m = c2 & all_eq3(B, C, D, Q) & none_eq2(B, F, _shift(src, -2, 1))
        assign(m, [K, J], J)          # K = J

    outer = (F != D)
    if outer.any():
        c1 = outer & (D != I) & (D != E) & (D != C)
        m = c1 & all_eq3(D, A, H, S) & none_eq2(D, B, _shift(src, 1, 2))
        assign(m, [J, L], L)          # J = L
        m = c1 & all_eq3(D, G, B, P) & none_eq2(D, H, _shift(src, 1, -2))
        assign(m, [L, J], J)          # L = J

        c2 = outer & (F != E) & (F != A) & (F != G)
        m = c2 & all_eq3(F, C, H, S) & none_eq2(F, B, _shift(src, -1, 2))
        assign(m, [K, M], M)          # K = M
        m = c2 & all_eq3(F, I, B, P) & none_eq2(F, H, _shift(src, -1, -2))
        assign(m, [M, K], K)          # M = K

    # 组装 2x 输出：[[J,K],[L,M]]
    out = np.empty((h * 2, w * 2), dtype=np.uint32)
    out[0::2, 0::2] = J
    out[0::2, 1::2] = K
    out[1::2, 0::2] = L
    out[1::2, 1::2] = M
    res = _unpack(out)

    if img.shape[2] == 4:
        # alpha 也用 nearest 方式 2x（MMPX 不处理 alpha 通道本身）
        a2 = np.repeat(np.repeat(img[:, :, 3], 2, axis=0), 2, axis=1)
        return np.concatenate([res, a2[:, :, None]], axis=2)
    return res


if __name__ == "__main__":
    # 自检：4x4 对角线与实心块
    t = np.zeros((6, 6, 3), np.uint8)
    t[0:3, 0:3] = 200          # 左上实心块
    t[3:6, 3:6] = 100          # 右下实心块
    r = mmpx2x(t)
    print("in ", t.shape, "out", r.shape)
    print("角块是否保持纯净:", r[0:6, 0:6].mean(), r[6:12, 6:12].mean())
