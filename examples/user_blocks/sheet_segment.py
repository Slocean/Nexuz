"""合板序列帧切分（sheet_segment）— Nexuz 用户自定义积木。

重叠感知的精灵表切帧：帧位相对均匀网格可漂移（±100px 量级）、相邻帧披风/
兵器横向越格互压时，宫格划分（sprite_sheet_cut）与连通域切割（transparent_cut）
都会切进精灵身体或整行粘连。本积木按「属于哪个精灵」做像素级归属再逐帧紧裁：
底部脚区（最不易粘连）定位真实帧中心 → 腐蚀分离出 N 个主体作种子 →
cv2.watershed 在白底合成图上按颜色轮廓脊线把重叠像素归属到正确帧（上层精灵
描边形成脊线，正是"人眼切分线"）；分水岭对深度粘连表不可靠（盔甲描边把内部
隔成小室，洪水串舱）时自动回退缝线切分：每条边界在背景缝里 DP 穿一条上下贯通
的最小偏移路径，翅膀互压堵死的行直线打穿。

切出帧（紧裁、画布=内容包围盒）直接喂 image_scale（行走类逐帧顶格）或
frames_normalize（攻击类锚点归一）。互不粘连、网格规整的简单合板请继续用
sprite_sheet_cut。依赖 OpenCV（主程序自带 opencv-python-headless）。

安装：放入 %LOCALAPPDATA%/Nexuz/user_blocks/ 并在设置中授权，重启后生效。
设计来源：三十六计_Nexuz序列帧切分与归一积木设计_v2.0（与仓库侧基线脚本
slice_vertical_walk.py 算法同构：帧中心定位、种子、分水岭、缝线 DP 公式一致）。
本机可信插件：隔离 worker 禁止网络与子进程、允许文件读写；请仅授权可信来源。
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np

SCHEMA = {
    "type": "sheet_segment",
    "label": "合板序列帧切分",
    "category": "识别类",
    "done_log": "已切分{{sheets}}张合板，共{{frames}}帧：{{first_path}}",
    "description": "重叠感知的精灵表切帧：脚区定位真实帧中心，分水岭沿轮廓脊线归属"
    "重叠像素，深度粘连自动回退缝线切分；逐帧紧裁输出，帧位漂移/披风兵器越格"
    "互压的合板专用。本机可信插件：隔离 worker 禁止网络与子进程、允许文件读写。",
    "inputs": [
        {
            "name": "image_path",
            "type": "string",
            "label": "合板路径",
            "default": "",
            "placeholder": "精灵合板图片，一行一张（批量）",
            "ui": "textarea",
            "bindable": True,
            "required": True,
        },
        {
            "name": "rows",
            "type": "number",
            "label": "行带数",
            "default": 2,
            "placeholder": "行投影自动检测的校验值，不符记入 errors；0=不校验",
        },
        {
            "name": "frames_per_row",
            "type": "number",
            "label": "每行帧数",
            "default": 0,
            "placeholder": "0=自动（脚区组件计数+多档行高分位投票）",
        },
        {
            "name": "direction_rows",
            "type": "string",
            "label": "行语义",
            "default": "down,up",
            "placeholder": "各行带语义与输出命名，按行序逗号分隔（如 down,up）",
        },
        {
            "name": "tight_crop",
            "type": "select",
            "label": "紧裁",
            "options": ["yes", "no"],
            "default": "yes",
            "option_labels": {
                "yes": "按内容包围盒紧裁（默认，喂给归一化）",
                "no": "保留行带画布（内容位置不变）",
            },
        },
        {
            "name": "max_aspect",
            "type": "number",
            "label": "宽高比上限",
            "default": 3,
            "placeholder": "帧内容宽/高超过该值视为切分异常，记入 errors；0=不检查",
        },
        {
            "name": "output_dir",
            "type": "string",
            "label": "输出目录",
            "default": "",
            "placeholder": "留空=输入旁的 图名_seg/行语义/；多张合板时按图名分子目录",
            "ui": "file_or_dir",
        },
    ],
    "outputs": [
        {"name": "ok", "type": "boolean"},
        {"name": "frames", "type": "number"},
        {"name": "sheets", "type": "number"},
        {"name": "first_path", "type": "string"},
        {"name": "paths", "type": "array"},
        {"name": "per_row", "type": "array"},
        {"name": "errors", "type": "array"},
    ],
}

# 内容判定：alpha > 16 视为有效像素（与设计文档参照脚本一致）
_ALPHA_THRESHOLD = 16
# 脚区行高分位档（由高到低：脚/腿是全带最不易粘连的区域）
_FOOT_FRACS = (0.72, 0.66, 0.78, 0.6, 0.84)
# 自动帧数候选上限
_MAX_CANDIDATE_FRAMES = 16
# 帧面积合理性守卫：任一帧 < 中位面积 30% 视为被邻帧吞并
_MIN_AREA_RATIO = 0.3
# 行带外扩边距：分水岭/缝线在带缘留一点背景余量
_BAND_MARGIN = 2


def _split_paths(raw: Any) -> list[Path]:
    """多行/列表 → 去重后的路径列表（兼容绑定上游输出的数组）。"""
    if isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        parts = str(raw or "").replace(";", "\n").splitlines()
    out: list[Path] = []
    seen: set[str] = set()
    for part in parts:
        text = str(part).strip().strip('"').strip("'")
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(Path(text))
    return out


def _row_bands(mask: np.ndarray) -> list[tuple[int, int]]:
    """按行投影找内容行带（半开区间 [start, end)）。"""
    rows = mask.any(axis=1)
    bands: list[tuple[int, int]] = []
    start: int | None = None
    for y, v in enumerate(rows):
        if v and start is None:
            start = y
        elif not v and start is not None:
            bands.append((start, y))
            start = None
    if start is not None:
        bands.append((start, len(rows)))
    return bands


def _snap_inside(mask: np.ndarray, x: int, y: int, max_r: int = 120) -> tuple[int, int] | None:
    """在 mask 内就近找一点（质心可能落在凹形区域之外）。"""
    for r in range(0, max_r):
        yy0, yy1 = max(0, y - r), min(mask.shape[0], y + r + 1)
        xx0, xx1 = max(0, x - r), min(mask.shape[1], x + r + 1)
        ys, xs = np.where(mask[yy0:yy1, xx0:xx1] > 0)
        if len(ys) > 0:
            return int(ys[0] + yy0), int(xs[0] + xx0)
    return None


def _foot_centers(
    band_mask: np.ndarray, nf: int, frac: float
) -> tuple[list[int], float, float] | None:
    """从行带底部脚区定位 nf 个真实帧中心 x。

    脚区组件位置是真值（帧位漂移鲁棒）；相邻精灵披风粘连（组件少于帧数）时
    共享组件在两格位之间的列密度谷处二分。成功返回 ( centers, 脚区大连通组件
    已解释面积占比, 平均相对偏差 )，失败返回 None。
    """
    H, band_w = band_mask.shape
    cell = band_w / nf
    zone = band_mask[int(H * frac):, :].astype(np.uint8)
    total = int(zone.sum())
    if total < 100:
        return None
    n, _, stats, cents = cv2.connectedComponentsWithStats(zone, connectivity=8)
    big = sorted(
        (i for i in range(1, n) if int(stats[i, cv2.CC_STAT_AREA]) >= max(50, 0.01 * total)),
        key=lambda i: -int(stats[i, cv2.CC_STAT_AREA]),
    )
    if len(big) < nf - 1:
        return None
    comps = big[:nf]
    owner: dict[int, int] = {}
    devs: list[float] = []
    for j in range(nf):
        expect = (j + 0.5) * cell
        comp = min(comps, key=lambda i: abs(cents[i][0] - expect))
        if abs(cents[comp][0] - expect) > 0.45 * cell:
            return None
        owner[j] = comp
        devs.append(abs(cents[comp][0] - expect) / cell)
    used: dict[int, list[int]] = {}
    for j, comp in owner.items():
        used.setdefault(comp, []).append(j)
    if any(len(js) > 2 for js in used.values()):
        return None
    centers: list[float] = [np.nan] * nf
    for comp, js in used.items():
        if len(js) == 1:
            centers[js[0]] = float(cents[comp][0])
            continue
        # 粘连对：组件在两格位之间找列密度谷切开，各自取块质心
        j0, j1 = min(js), max(js)
        sub = np.where(zone == comp, 1, 0).astype(np.uint8)
        lo = int(max(0, (j0 + 0.25) * cell))
        hi = int(min(band_w, (j1 + 0.75) * cell))
        xm = lo + int(np.argmin(sub[:, lo:hi].sum(axis=0)))
        for j, (a, b) in ((j0, (0, xm)), (j1, (xm, band_w))):
            pys, pxs = np.where(sub[:, a:b] > 0)
            if len(pys) == 0:
                return None
            centers[j] = float(pxs.mean()) + a
    if any(np.isnan(c) for c in centers):
        return None
    explained = sum(int(stats[c, cv2.CC_STAT_AREA]) for c in used) / max(
        1, sum(int(stats[c, cv2.CC_STAT_AREA]) for c in big)
    )
    return [int(round(c)) for c in centers], explained, float(np.mean(devs))


def _locate_centers(band_mask: np.ndarray, nf: int) -> list[int] | None:
    """多档脚区分位逐档尝试，取首个成功档位的帧中心。"""
    for frac in _FOOT_FRACS:
        res = _foot_centers(band_mask, nf, frac)
        if res is not None:
            return res[0]
    return None


def _spacing_consistent(centers: list[int]) -> float | None:
    """帧中心等距性校验：返回间距变异系数；间距异常（漏帧/重帧）返回 None。

    排除自动帧数检测的两类假阳性：某精灵脚部分裂成两块会把候选帧数抬高
    （帧中心呈"小间距/大间距"交替，cv≈0.2；真值帧距来自生成网格，cv<0.1），
    漏检一格会压低帧数（出现过大间距）。
    """
    if len(centers) < 2:
        return 0.0
    diffs = np.diff(np.asarray(centers, dtype=np.float64))
    mean = float(diffs.mean())
    if mean <= 0:
        return None
    cv = float(diffs.std() / mean)
    if cv > 0.12 or float(diffs.min()) < 0.35 * mean or float(diffs.max()) > 1.8 * mean:
        return None
    return cv


def _detect_frame_count(band_mask: np.ndarray) -> int | None:
    """自动帧数：多档行高分位投票，每档取「脚区组件能按格位认领（含粘连对
    二分）且已解释面积 ≥90%、帧中心等距」的最优候选；平票取较大帧数。"""
    votes: list[int] = []
    for frac in _FOOT_FRACS:
        best: tuple[float, int] | None = None
        for nf in range(1, _MAX_CANDIDATE_FRAMES + 1):
            res = _foot_centers(band_mask, nf, frac)
            if res is None:
                continue
            centers, ratio, mean_dev = res
            if ratio < 0.9:
                continue
            cv = _spacing_consistent(centers)
            if cv is None:
                continue
            score = cv + mean_dev
            if best is None or score < best[0]:
                best = (score, nf)
        if best is not None:
            votes.append(best[1])
    if not votes:
        return None
    counts = Counter(votes)
    top = max(counts.values())
    return max(nf for nf, v in counts.items() if v == top)


def _valley_cuts(band_mask: np.ndarray, nf: int) -> list[int]:
    """边界切点：优先用脚区真实帧中心的中点（漂移鲁棒），缺底时退回均匀网格
    中点 ±0.2 格内密度最稀列。缝线切分以这些点为起点穿缝。"""
    band_mask_u8 = band_mask.astype(np.uint8)
    cell = band_mask.shape[1] / nf
    centers = _locate_centers(band_mask, nf)
    cuts = [0]
    for j in range(1, nf):
        if centers is not None:
            cuts.append((centers[j - 1] + centers[j]) // 2)
            continue
        density = band_mask_u8.sum(axis=0)
        lo = max(cuts[-1] + 1, int(round(j * cell - 0.2 * cell)))
        hi = min(band_mask.shape[1] - 1, int(round(j * cell + 0.2 * cell)))
        cuts.append(lo + int(np.argmin(density[lo : hi + 1])))
    cuts.append(band_mask.shape[1])
    return cuts


def _gap_path(band_mask: np.ndarray, xm: int, max_dev: int) -> np.ndarray | None:
    """在预期切点 xm 附近构造上下贯通的边界路径（2px 网格位置作状态）。

    缝道斜向蜿蜒且可能在翅膀相触的行被完全堵死：背景行只能走背景像素，堵死
    的行放开全格打穿内容（+50 罚），代价=Σ|x−xm|，相邻行位移 ≤±6px。
    ±max_dev 限制防串到邻边界；无解返回 None，调用方退回直线。
    """
    bg = ~band_mask.astype(bool)
    H, W = bg.shape
    INF = np.int64(1) << 40
    grid = np.arange(max(0, xm - max_dev), min(W, xm + max_dev + 1), 2)
    n = len(grid)
    if n == 0:
        return None
    dev = np.abs(grid - xm).astype(np.int64)
    cost = np.full(n, INF, dtype=np.int64)
    valid = bg[0, grid]
    if valid.any():
        cost[valid] = dev[valid]
    else:
        cost[:] = dev + 50  # 首行即堵死，全放开打穿
    parents = np.zeros((H, n), dtype=np.int32)
    shifts = range(-3, 4)
    for y in range(1, H):
        valid = bg[y, grid]
        blocked = not valid.any()
        if blocked:
            valid = np.ones(n, dtype=bool)
        cand = np.where(valid, dev + (50 if blocked else 0), INF)
        stack = np.full((7, n), INF, dtype=np.int64)
        for si, k in enumerate(shifts):
            if k < 0:
                stack[si, :k] = cost[-k:]
            elif k > 0:
                stack[si, k:] = cost[:-k]
            else:
                stack[si] = cost
        from_idx = np.argmin(stack, axis=0)
        best = stack[from_idx, np.arange(n)]
        cost = best + cand
        # stack[k][i] = cost[i-k]：列 i 的前驱是 i-k，k=from_idx-3
        parents[y] = np.arange(n) - (from_idx - 3)
    i = int(np.argmin(cost))
    if cost[i] >= INF:
        return None
    xs = np.zeros(H, dtype=np.int64)
    xs[H - 1] = grid[i]
    for y in range(H - 1, 0, -1):
        j = int(parents[y, i])
        if j < 0 or j >= n:
            return None
        i = j
        xs[y - 1] = grid[i]
    return xs


def _seeds_by_erosion(band_mask: np.ndarray, nf: int) -> np.ndarray:
    """腐蚀到分离出 nf 大块作种子；相邻两格位共享同一组件=粘连对，在密度谷
    切开取种。"""
    band_mask_u8 = band_mask.astype(np.uint8)
    total = int(band_mask_u8.sum())
    cell = band_mask.shape[1] / nf
    for k in range(3, 91, 2):
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        eroded = cv2.erode(band_mask_u8, kernel)
        n, label_img, stats, cents = cv2.connectedComponentsWithStats(eroded, connectivity=8)
        big = [i for i in range(1, n) if int(stats[i, cv2.CC_STAT_AREA]) >= max(64, 0.02 * total)]
        if len(big) < nf:
            continue
        # 每个格位认领质心最近的组件
        nearest: dict[int, int] = {}
        for j in range(nf):
            expect = (j + 0.5) * cell
            comp = min(big, key=lambda i: abs(cents[i][0] - expect))
            if abs(cents[comp][0] - expect) > cell / 2:
                break
            nearest[j] = comp
        if len(nearest) != nf:
            continue
        used: dict[int, list[int]] = {}
        for j, comp in nearest.items():
            used.setdefault(comp, []).append(j)
        if any(len(js) > 2 for js in used.values()):
            continue
        seed_pts: list[tuple[int, int] | None] = [None] * nf
        ok = True
        for comp, js in used.items():
            if len(js) == 1:
                x, y = int(round(cents[comp][0])), int(round(cents[comp][1]))
                pt = _snap_inside(eroded, x, y)
                if pt is None:
                    ok = False
                    break
                seed_pts[js[0]] = pt
                continue
            # 粘连对：两格位之间找密度谷切开组件，各自取质心
            j0, j1 = min(js), max(js)
            lo = int((j0 + 0.9) * cell)
            hi = int((j1 + 0.1) * cell)
            col_density = eroded[:, lo:hi].sum(axis=0)
            xm = lo + int(np.argmin(col_density))
            for j, (a, b) in ((j0, (0, xm)), (j1, (xm, eroded.shape[1]))):
                part = np.where(label_img[:, a:b] == comp, 1, 0).astype(np.uint8)
                if part.sum() == 0:
                    ok = False
                    break
                pys, pxs = np.where(part > 0)
                pt = _snap_inside(part, int(pxs.mean()), int(pys.mean()))
                if pt is None:
                    ok = False
                    break
                # part 的 x 坐标相对全图偏移 a，种子点要加回
                seed_pts[j] = (pt[0], pt[1] + a)
        if not ok or any(p is None for p in seed_pts):
            continue
        markers = np.zeros(band_mask.shape, dtype=np.int32)
        for j, (y, x) in enumerate(seed_pts):
            markers[y, x] = j + 2
        return markers
    raise RuntimeError("腐蚀未能分离出合法种子（含粘连对谷切仍失败）")


def _seeds_by_valley(band_mask: np.ndarray, nf: int) -> np.ndarray:
    """密度谷兜底种子（深度粘连表，如展翅）：谷线分窗，每窗腐蚀取最大组件
    （本帧躯干）质心吸附作种子。种子只需落对本帧。"""
    band_mask_u8 = band_mask.astype(np.uint8)
    cuts = _valley_cuts(band_mask, nf)
    markers = np.zeros(band_mask.shape, dtype=np.int32)
    for j in range(nf):
        sub = band_mask_u8[:, cuts[j] : cuts[j + 1]]
        eroded = cv2.erode(sub, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
        n, _, stats, cents = cv2.connectedComponentsWithStats(eroded, connectivity=8)
        if n <= 1:
            raise RuntimeError(f"密度谷窗 {j + 1} 无主体")
        comp = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y = int(round(cents[comp][0])), int(round(cents[comp][1]))
        pt = _snap_inside(eroded, x, y)
        if pt is None:
            raise RuntimeError(f"密度谷窗 {j + 1} 种子吸附失败")
        markers[pt[0], pt[1] + cuts[j]] = j + 2
    return markers


def _find_seed_markers(band_mask: np.ndarray, nf: int) -> np.ndarray:
    """分水岭种子标记图（int32，0=未知，2..nf+1=帧）。腐蚀法优先，密度谷兜底。"""
    try:
        return _seeds_by_erosion(band_mask, nf)
    except RuntimeError:
        return _seeds_by_valley(band_mask, nf)


def _watershed_frames(
    band_img: np.ndarray, band_mask: np.ndarray, content: np.ndarray, nf: int
) -> list[np.ndarray]:
    markers = _find_seed_markers(band_mask, nf)
    markers[~content] = 1  # 背景种子（0 保留为未知，交给洪水填充）
    # 合成到白底再做分水岭：透明区直转 BGR 是纯黑，与深色描边梯度≈0，背景洪水
    # 会吞掉描边；白底与描边对比强烈，脊线正好落在轮廓上
    alpha = band_img[..., 3:4].astype(np.float32) / 255.0
    over_white = (band_img[..., :3].astype(np.float32) * alpha + 255.0 * (1.0 - alpha)).astype(
        np.uint8
    )
    bgr = cv2.cvtColor(over_white, cv2.COLOR_RGB2BGR)
    cv2.watershed(bgr, markers)
    frames: list[np.ndarray] = []
    for rank in range(nf):
        fm = (markers == rank + 2) & content
        frames.append(fm.astype(np.uint8))
    # 描边/分界像素（标签 1 或 -1 的内容像素）按连通就近竞争归还相邻帧，避免轮廓被吞
    unclaimed = content & ~(markers >= 2)
    kernel3 = np.ones((3, 3), np.uint8)
    for _ in range(256):
        if not unclaimed.any():
            break
        progressed = False
        for fm in frames:
            if not unclaimed.any():
                break
            grown = cv2.dilate(fm, kernel3) > 0
            take = unclaimed & grown
            if take.any():
                fm[take] = 1
                unclaimed &= ~take
                progressed = True
        if not progressed:
            break
    if unclaimed.any():
        # 与所有主体不连通的悬空碎片（如脱离轮廓的刀刃）：按最近帧距离归属
        dist = np.full((nf, *content.shape), np.inf, dtype=np.float32)
        for fi, fm in enumerate(frames):
            dist[fi] = cv2.distanceTransform((~fm.astype(bool)).astype(np.uint8), cv2.DIST_L2, 3)
        nearest = np.argmin(dist, axis=0)
        for fi, fm in enumerate(frames):
            take = unclaimed & (nearest == fi)
            if take.any():
                fm[take] = 1
        unclaimed = content & ~np.logical_or.reduce([fm.astype(bool) for fm in frames])
    if unclaimed.any():
        raise RuntimeError(f"{int(unclaimed.sum())} 个内容像素未能归属任何帧")
    out: list[np.ndarray] = []
    for rank in range(nf):
        fm = frames[rank]
        if fm.sum() == 0:
            raise RuntimeError(f"分水岭第 {rank + 1} 帧为空")
        out.append(fm.astype(np.uint8))
    return out


def _segment_band(
    band_img: np.ndarray, band_mask: np.ndarray, nf: int
) -> tuple[list[np.ndarray], str]:
    """切分一行带为 nf 帧掩码。首选分水岭（重叠像素沿上层精灵轮廓脊线归属）；
    深度粘连表（盔甲描边把内部隔成小室，洪水串舱不可靠）回退缝线切分：每条
    边界在背景缝里穿上下贯通的最小偏移路径沿缝切（翅膀互压堵死的行打穿），
    逐行单调守卫防两条边界穿进同一条缝。返回 (帧掩码, 切分策略)。"""
    content = band_mask.astype(bool)
    try:
        return _sanity_frames(_watershed_frames(band_img, band_mask, content, nf)), "watershed"
    except RuntimeError:
        cuts = _valley_cuts(band_mask, nf)
        H = content.shape[0]
        bounds: list[np.ndarray] = [np.zeros(H, dtype=np.int64)]
        max_dev = max(48, int(0.28 * band_mask.shape[1] / nf))
        for j in range(1, nf):
            p = _gap_path(band_mask, cuts[j], max_dev)
            bounds.append(p if p is not None else np.full(H, cuts[j], dtype=np.int64))
        bounds.append(np.full(H, band_mask.shape[1], dtype=np.int64))
        # 越界者退回直线
        for j in range(1, nf):
            if (bounds[j] < bounds[j - 1]).any() or (bounds[j] >= bounds[j + 1]).any():
                bounds[j] = np.full(H, cuts[j], dtype=np.int64)
        col = np.arange(band_mask.shape[1])[None, :]
        frames: list[np.ndarray] = []
        for j in range(nf):
            fm = np.zeros_like(content, dtype=np.uint8)
            fm[(col >= bounds[j][:, None]) & (col < bounds[j + 1][:, None]) & content] = 1
            if fm.sum() == 0:
                raise RuntimeError(f"缝线切分第 {j + 1} 帧为空")
            frames.append(fm)
        return _sanity_frames(frames), "gap_path"


def _sanity_frames(frames: list[np.ndarray]) -> list[np.ndarray]:
    """帧面积合理性守卫：任一帧 < 中位面积 30% 视为被邻帧吞并。"""
    areas = [int(fm.sum()) for fm in frames]
    median = float(np.median(areas))
    for rank, a in enumerate(areas):
        if a < _MIN_AREA_RATIO * median:
            raise RuntimeError(f"第 {rank + 1} 帧面积 {a} < 中位 {median:.0f} 的 30%，疑似被邻帧吞并")
    return frames


def _cut_band(
    sheet: np.ndarray,
    band: tuple[int, int],
    nf: int,
    label: str,
    out_dir: Path,
    *,
    tight_crop: bool,
    max_aspect: float,
    errors: list[str],
) -> tuple[list[str], dict[str, Any]]:
    """切分一行带并写出帧文件；问题记入 errors。返回 (路径, 行明细)。"""
    y0, y1 = band
    m = _BAND_MARGIN
    band_img = sheet[max(0, y0 - m) : y1 + m]
    band_mask = (sheet[..., 3] > _ALPHA_THRESHOLD)[max(0, y0 - m) : y1 + m]
    try:
        frames, strategy = _segment_band(band_img, band_mask, nf)
    except RuntimeError as exc:
        errors.append(f"{label}：切分失败（{exc}）")
        return [], {}

    boxes: list[tuple[int, int, int, int]] = []
    for fm in frames:
        ys, xs = np.where(fm > 0)
        boxes.append((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))

    aspect_rejects: list[int] = []
    if max_aspect > 0:
        for fi, (x0, yy0, x1, yy1) in enumerate(boxes):
            cw, ch = x1 - x0, yy1 - yy0
            if ch > 0 and cw / ch > max_aspect:
                aspect_rejects.append(fi)
                errors.append(
                    f"{label}第 {fi + 1} 帧：内容 {cw}x{ch} 宽高比超限（>{max_aspect:g}），已跳过"
                )
    if len(aspect_rejects) >= nf:
        errors.append(f"{label}：全部帧宽高比超限，整行放弃")
        return [], {}

    out_dir.mkdir(parents=True, exist_ok=True)
    band_h, band_w = band_mask.shape
    paths: list[str] = []
    sizes: list[list[int]] = []
    kept_boxes: list[list[int]] = []
    for fi, fm in enumerate(frames):
        if fi in aspect_rejects:
            continue
        x0, yy0, x1, yy1 = boxes[fi]
        if tight_crop:
            cw, ch = x1 - x0, yy1 - yy0
            crop = band_img[yy0:yy1, x0:x1].copy()
            crop[fm[yy0:yy1, x0:x1] == 0] = 0  # 帧外像素清透明
        else:
            # 保留行带画布，内容位置不变
            cw, ch = band_w, band_h
            crop = band_img.copy()
            crop[fm == 0] = 0
        name = out_dir / f"{label}_{fi + 1:02d}.png"
        # 内部按 RGBA 语义处理（与参照脚本一致），写出转回 OpenCV 的 BGRA
        ok_enc, buf = cv2.imencode(".png", cv2.cvtColor(crop, cv2.COLOR_RGBA2BGRA))
        if not ok_enc:
            errors.append(f"{label}第 {fi + 1} 帧：PNG 编码失败")
            continue
        buf.tofile(str(name))
        paths.append(str(name))
        sizes.append([cw, ch])
        kept_boxes.append([x0, yy0, x1, yy1])

    detail = {
        "label": label,
        "frames": len(paths),
        "strategy": strategy,
        "sizes": sizes,
        "boxes": kept_boxes,
    }
    return paths, detail


def _cut_sheet(
    src: Path, sheet: np.ndarray, labels: list[str], nf: int | None, rows_check: int,
    out_root: Path, *, tight_crop: bool, max_aspect: float, errors: list[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    """切一张合板：行带数校验 → 逐行切分写出。返回 (路径, 行明细)。"""
    mask = sheet[..., 3] > _ALPHA_THRESHOLD
    bands = _row_bands(mask)
    if rows_check > 0 and len(bands) != rows_check:
        errors.append(f"{src.name}：行带数 {len(bands)} ≠ {rows_check}，已跳过")
        return [], []
    if len(bands) != len(labels):
        errors.append(
            f"{src.name}：行带数 {len(bands)} 与行语义数 {len(labels)} 不一致，已跳过"
        )
        return [], []

    paths: list[str] = []
    details: list[dict[str, Any]] = []
    for band_i, (band, label) in enumerate(zip(bands, labels)):
        row_nf = nf
        if row_nf is None:
            row_mask = mask[band[0] : band[1]]
            row_nf = _detect_frame_count(row_mask)
            if row_nf is None:
                errors.append(f"{src.name} 第 {band_i + 1} 行（{label}）：帧数不明，该行跳过")
                continue
        row_paths, detail = _cut_band(
            sheet,
            band,
            row_nf,
            label,
            out_root / label,
            tight_crop=tight_crop,
            max_aspect=max_aspect,
            errors=errors,
        )
        if detail:
            detail["sheet"] = src.name
            detail["frame_count"] = row_nf
            details.append(detail)
        paths.extend(row_paths)
    return paths, details


def _load_sheet(src: Path) -> np.ndarray:
    """读图为 RGBA（imdecode 走字节流，兼容 Windows 非 ASCII 路径）。"""
    raw = np.fromfile(str(src), dtype=np.uint8)
    data = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
    if data is None:
        raise ValueError(f"图片解码失败: {src}")
    if data.ndim == 2:
        data = cv2.cvtColor(data, cv2.COLOR_GRAY2BGRA)
    if data.shape[2] == 3:
        data = cv2.cvtColor(data, cv2.COLOR_BGR2RGBA)
        return data
    if data.shape[2] == 4:
        # 统一按 RGBA 通道语义处理（imdecode 给的是 BGRA）
        return cv2.cvtColor(data, cv2.COLOR_BGRA2RGBA)
    raise ValueError(f"不支持的图片通道数: {src}")


def handler(params, context, **kwargs):
    sources = _split_paths(params.get("image_path"))
    if not sources:
        raise ValueError("image_path 不能为空（每行一个合板路径）")

    rows_check = int(float(params.get("rows") if params.get("rows") is not None else 2) or 0)
    nf = int(float(params.get("frames_per_row") if params.get("frames_per_row") is not None else 0))
    nf = nf if nf > 0 else None
    labels = [t.strip() for t in str(params.get("direction_rows") or "down,up").split(",") if t.strip()]
    if not labels:
        raise ValueError("direction_rows 行语义不能为空")
    if len(set(labels)) != len(labels):
        raise ValueError(f"direction_rows 行语义重复: {labels}")
    tight_crop = str(params.get("tight_crop") or "yes") != "no"
    max_aspect = float(params.get("max_aspect") if params.get("max_aspect") is not None else 3)

    for src in sources:
        if not src.is_file():
            raise FileNotFoundError(f"合板不存在: {src}")

    raw_out = str(params.get("output_dir") or "").strip().strip('"').strip("'")
    out_root = Path(raw_out) if raw_out else None

    all_paths: list[str] = []
    all_details: list[dict[str, Any]] = []
    errors: list[str] = []
    for src in sources:
        try:
            sheet = _load_sheet(src)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if out_root is not None:
            # 显式输出目录：单张直接用，多张按图名分子目录
            sheet_out = out_root if len(sources) == 1 else out_root / src.stem
        else:
            sheet_out = src.parent / f"{src.stem}_seg"
        sheet_paths, sheet_details = _cut_sheet(
            src,
            sheet,
            labels,
            nf,
            rows_check,
            sheet_out,
            tight_crop=tight_crop,
            max_aspect=max_aspect,
            errors=errors,
        )
        all_paths.extend(sheet_paths)
        all_details.extend(sheet_details)

    return {
        "ok": not errors,
        "frames": len(all_paths),
        "sheets": len(sources),
        "first_path": all_paths[0] if all_paths else "",
        "paths": all_paths,
        "per_row": all_details,
        "errors": errors,
    }
