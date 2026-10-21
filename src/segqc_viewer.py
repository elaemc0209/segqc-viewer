# -*- coding: utf-8 -*-
"""
膀胱分割人工质控看图器 (Bladder Seg QC Viewer)

面向没有计算机基础的审核人：双击 exe -> 选一次 CT 文件夹 -> 滚轮翻层看叠加 -> 点结论。
结果自动写入同目录 质控结果.csv，评完把该文件发回即可。

依赖：numpy / pydicom / pillow / tkinter（全部打进 exe）
"""
from __future__ import annotations

import argparse
import csv
import gc
import glob
import gzip
import json
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np
import pydicom
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from PIL import Image, ImageTk

APP_TITLE = "膀胱分割质控看图器"
VERSION = "1.4.0"
OUTPUT_DIR = None
CT_ROOT = None
MASK_DIR = None

# ---------------- 配色 ----------------
BG = "#0f1319"
BG2 = "#171d26"
BG3 = "#222b38"
FG = "#e8edf2"
FG2 = "#9aa8b8"
ACCENT = "#4aa8ff"
C_PASS = "#2e7d4f"
C_MINOR = "#b8860b"
C_FAIL = "#b23a3a"
C_EXCL = "#5e4b8b"
C_FLAG = "#ff6b6b"

GRADES = [("pass", "通过", C_PASS, "1"),
          ("minor", "轻微问题", C_MINOR, "2"),
          ("fail", "失败需重做", C_FAIL, "3"),
          ("exclude", "该例排除", C_EXCL, "4")]

# 分割显示方式：填充 / 仅轮廓 / 隐藏
MASK_MODES = [("fill", "填充"), ("outline", "仅轮廓"), ("off", "隐藏")]
MASK_MODE_ORDER = [m for m, _ in MASK_MODES]

# 评分表用到的短标签与行颜色
GRADE_LABEL = {"pass": "通过", "minor": "轻微", "fail": "失败", "exclude": "排除"}
GRADE_FG = {"pass": "#6ee7a8", "minor": "#ffc857", "fail": "#ff8b8b", "exclude": "#c3a6ff"}


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


# ============================================================
# 读文件：NIfTI(.nii.gz) 掩膜
# ============================================================
def data_dir() -> Path:
    return OUTPUT_DIR if OUTPUT_DIR is not None else app_dir()


def read_nifti_gz(path):
    """最小 NIfTI-1 读取器 -> (z, y, x) 数组 + spacing(x,y,z)"""
    with gzip.open(path, "rb") as f:
        hdr = f.read(348)
        if len(hdr) < 348:
            raise ValueError("文件过短，不是 NIfTI")
        endian = "<"
        if struct.unpack("<i", hdr[0:4])[0] != 348:
            if struct.unpack(">i", hdr[0:4])[0] == 348:
                endian = ">"
            else:
                raise ValueError("不是 NIfTI-1 文件")

        dim = struct.unpack(endian + "8h", hdr[40:56])
        ndim = int(dim[0])
        shape = tuple(int(x) for x in dim[1:1 + ndim])
        if ndim != 3 or any(d <= 0 for d in shape):
            raise ValueError("仅支持三维 NIfTI-1 掩膜")
        if hdr[344:348] != b"n+1\x00":
            raise ValueError("仅支持单文件 NIfTI-1 (.nii.gz)")
        if struct.unpack(endian + "h", hdr[254:256])[0] <= 0:
            raise ValueError("掩膜必须提供有效 sform；请先转换到与 CT 一致的空间网格")
        if hdr[123] & 7 != 2:
            raise ValueError("掩膜空间单位必须为毫米")
        affine = np.eye(4)
        affine[:3] = np.array(struct.unpack(endian + "12f", hdr[280:328])).reshape(3, 4)
        affine = np.diag([-1., -1., 1., 1.]) @ affine  # NIfTI RAS -> DICOM LPS
        if not np.isfinite(affine).all() or abs(np.linalg.det(affine[:3, :3])) < 1e-8:
            raise ValueError("掩膜 sform 无效")
        datatype = struct.unpack(endian + "h", hdr[70:72])[0]
        pixdim = struct.unpack(endian + "8f", hdr[76:108])
        vox_offset = int(struct.unpack(endian + "f", hdr[108:112])[0])
        if vox_offset < 352:
            raise ValueError("NIfTI 数据偏移无效")
        slope = struct.unpack(endian + "f", hdr[112:116])[0]
        inter = struct.unpack(endian + "f", hdr[116:120])[0]
        if slope == 0:
            slope = 1.0

        dt = {2: "u1", 4: "i2", 8: "i4", 16: "f4", 64: "f8",
              256: "i1", 512: "u2", 768: "u4", 1024: "i8"}.get(datatype)
        if dt is None:
            raise ValueError(f"不支持的 NIfTI datatype={datatype}")

        if vox_offset > 348:
            f.seek(vox_offset)
        raw = f.read()

    n = int(np.prod(shape, dtype=np.int64))
    arr = np.frombuffer(raw, dtype=np.dtype(endian + dt), count=n)
    arr = arr.reshape(shape, order="F")          # NIfTI: x 变化最快
    if arr.ndim == 3:
        arr = np.ascontiguousarray(arr.transpose(2, 1, 0))   # -> (z, y, x)
    spacing = (float(pixdim[1]), float(pixdim[2]), float(pixdim[3]))
    if slope != 1.0 or inter != 0.0:
        arr = arr * slope + inter

    # z 轴方向：srow_z[2] 为负表示 k 递增时物理 z 递减（层序是“从上往下”）。
    # 各例不统一，必须据此决定 DICOM 的排序方向，否则整例会上下颠倒。
    dz = float(pixdim[3])
    z0 = 0.0
    if len(hdr) >= 328:
        srow_z = struct.unpack(endian + "4f", hdr[312:328])
        if abs(srow_z[2]) > 1e-6:
            dz = float(srow_z[2])
        z0 = float(srow_z[3])
    if not np.isfinite(arr).all():
        raise ValueError("掩膜包含非有限数值")
    meta = {"dz": dz, "z0": z0, "affine_lps": affine, "shape_xyz": shape}
    return arr, spacing, meta


# ============================================================
# 读文件：DICOM 序列
# ============================================================
def load_dicom_series(folder, expect_n=None, z_sign=1, z0=None, progress=None,
                      mask_geometry=None) -> tuple[np.ndarray, tuple]:
    """把 DICOM 序列读成 (z, y, x) int16 HU 数组 + spacing(x,y,z)

    expect_n : 期望层数（= 该例掩膜的层数）。同一位置可能被重复采集，
               不同病例的 NIfTI 有的去重、有的没去重，所以这里同时准备
               “原样”和“去重”两种版本，选层数对得上的那个。
    z_sign   : +1 表示掩膜的 k 递增对应物理 z 递增；-1 表示相反。
               必须与掩膜一致，否则层序会反向。
    """
    folder = str(folder)
    files = glob.glob(os.path.join(folder, "*.dcm"))
    if not files:
        files = [p for p in glob.glob(os.path.join(folder, "*"))
                 if os.path.isfile(p)]
    if not files:
        raise ValueError(f"目录里没有 DICOM 文件：{folder}")

    # 1) 读头，按法向投影排序
    items, iop = [], None
    for i, f in enumerate(files):
        try:
            ds = pydicom.dcmread(f, stop_before_pixels=True, force=True)
            ipp = np.array(ds.ImagePositionPatient, dtype=float)
            if iop is None:
                iop = np.array(ds.ImageOrientationPatient, dtype=float)
            items.append((ipp, f, ds))
        except Exception:
            continue
        if progress and i % 50 == 0:
            progress(f"正在读取影像 {i}/{len(files)} …")

    if not items:
        raise ValueError("DICOM 文件无法解析")
    series = {str(getattr(t[2], "SeriesInstanceUID", "")) for t in items}
    if len(series) != 1 or "" in series:
        raise ValueError("目录必须包含且仅包含一个有效 DICOM 序列")
    if any(getattr(t[2], "Modality", "") != "CT" or
           int(getattr(t[2], "NumberOfFrames", 1)) != 1 for t in items):
        raise ValueError("仅支持单帧 CT DICOM 序列")

    if iop is not None and len(iop) == 6:
        normal = np.cross(iop[:3], iop[3:])
        if normal[2] < 0:
            normal = -normal
    else:
        normal = np.array([0.0, 0.0, 1.0])
    # 方向判定：优先看“掩膜第 0 层落在 DICOM 的最低 z 还是最高 z”。
    # 少数病例的 NIfTI 数组是降序的，但 affine 里 dz 仍写成正（转换端的 bug），
    # 最终还必须通过完整空间网格核对。
    projs_all = [float(np.dot(t[0], normal)) for t in items]
    reverse = z_sign < 0
    if z0 is not None and projs_all:
        dmin, dmax = min(projs_all), max(projs_all)
        if abs(z0 - dmax) < abs(z0 - dmin) - 1e-6:
            reverse = True
        elif abs(z0 - dmin) < abs(z0 - dmax) - 1e-6:
            reverse = False

    # 排序方式要和当初生成 NIfTI 的规则一致，否则整例会错位。
    # 实测这批数据分两种：
    #   ① 重复采集很少 → NIfTI 按层面位置(z)排
    #   ② 重复采集很多 → 转换器放弃按位置排，改成按采集顺序(InstanceNumber)
    #      最终完整几何核对仍会拒绝不能对应规则体素网格的序列。
    _dup_ratio = 1.0 - len({round(float(np.dot(t[0], normal)), 2) for t in items}) / max(len(items), 1)
    sort_desc = "按层面位置"
    if expect_n == len(items) and _dup_ratio >= 0.10:
        items.sort(key=lambda t: int(getattr(t[2], "InstanceNumber", 0) or 0))
        sort_desc = "按采集顺序（重复层较多）"
    else:
        items.sort(key=lambda t: int(getattr(t[2], "InstanceNumber", 0) or 0))
        items.sort(key=lambda t: float(np.dot(t[0], normal)), reverse=reverse)

    # 同一层位置可能被重复采集（重扫）。不同病例的 NIfTI 有的去重、有的没去重，
    # 所以两个版本都留着，最后按“与该例掩膜层数一致”来选。
    uniq = {}
    for ipp, f, ds in items:
        key = round(float(np.dot(ipp, normal)), 2)
        inst = int(getattr(ds, "InstanceNumber", 0) or 0)
        if key not in uniq or inst > uniq[key][0]:
            uniq[key] = (inst, ipp, f, ds)
    dedup = [(ipp, f, ds) for _i, ipp, f, ds in
             sorted(uniq.values(), key=lambda t: float(np.dot(t[1], normal)), reverse=reverse)]
    if progress and sort_desc != "按层面位置":
        progress(sort_desc)

    variants = [(len(items), "原样", items)]
    if len(dedup) != len(items):
        variants.append((len(dedup), "合并重复层", dedup))

    if expect_n:
        chosen, chosen_name = None, ""
        for cnt, name, v in variants:
            if cnt == expect_n:
                chosen, chosen_name = v, name
                break
        if chosen is None:
            raise ValueError(
                f"DICOM 有 {len(items)} 个文件，合并重复采集后 {len(dedup)} 层，"
                f"都与该例分割的 {expect_n} 层对不上")
        if chosen_name != "原样" and progress:
            progress(f"{chosen_name}：{len(items)} → {len(chosen)} 层")
        items = chosen

    if mask_geometry is not None:
        validate_geometry(items, mask_geometry)

    # 2) 读像素
    ds0 = items[0][2]
    rows, cols = int(ds0.Rows), int(ds0.Columns)
    ps0 = getattr(ds0, "PixelSpacing", [1.0, 1.0])
    th0 = float(getattr(ds0, "SliceThickness", 1.0) or 1.0)
    projs = [t[0] for t in items]
    order = [t[1] for t in items]
    del items, ds0                      # 663 个 Dataset 到此就不再需要，及早放掉

    n = len(order)
    vol = np.empty((n, rows, cols), dtype=np.int16)
    for i, f in enumerate(order):
        ds = pydicom.dcmread(f, force=True)
        raw = ds.pixel_array
        # 个别文件的 BitsStored < 分配位数且高位有垃圾（例如
        # uint16 里出现 65535），必须按有效位掩码，否则 HU 会算成几万
        _bits = int(getattr(ds, "BitsStored", 0) or 0)
        _alloc = raw.dtype.itemsize * 8
        if 0 < _bits < _alloc and int(getattr(ds, "PixelRepresentation", 0)) == 0:
            raw = raw & np.array((1 << _bits) - 1, dtype=raw.dtype)
        px = raw.astype(np.float32)
        slope = float(getattr(ds, "RescaleSlope", 1) or 1)
        inter = float(getattr(ds, "RescaleIntercept", 0) or 0)
        vol[i] = np.clip(px * slope + inter, -32000, 32000).astype(np.int16)
        if progress and i % 60 == 0:
            progress(f"正在读取影像 {i}/{n} …")

    sx, sy = float(ps0[1]), float(ps0[0])
    if n > 1:
        zs = [float(np.dot(p, normal)) for p in projs]
        dz = abs(zs[-1] - zs[0]) / max(n - 1, 1)
    else:
        dz = th0
    return vol, (sx, sy, dz if dz > 0 else 1.0)


# ============================================================
# 病例定位
# ============================================================
def validate_geometry(items, meta):
    """Reject incompatible grids; displaying a same-shaped array is not registration."""
    affine = meta["affine_lps"]
    nx, ny, nz = meta["shape_xyz"]
    if len(items) != nz:
        raise ValueError("CT 与掩膜层数不一致")
    for k, (ipp, _, ds) in enumerate(items):
        iop = np.asarray(ds.ImageOrientationPatient, dtype=float)
        ps = np.asarray(ds.PixelSpacing, dtype=float)
        expected = affine[:3, 3] + k * affine[:3, 2]
        if (int(ds.Rows) != ny or int(ds.Columns) != nx or
            not np.allclose(iop[:3] * ps[1], affine[:3, 0], atol=1e-3, rtol=0) or
            not np.allclose(iop[3:] * ps[0], affine[:3, 1], atol=1e-3, rtol=0) or
            not np.allclose(ipp, expected, atol=0.1, rtol=0)):
            raise ValueError("CT 与掩膜空间网格不一致（方向、原点或间距）；请先配准/重采样")


def resolve_ct_root(root: Path):
    """把用户选的文件夹解析成“病例目录集合”，兼容三层布局"""
    if root is None:
        return None
    root = Path(root)
    cand = root / "影像"
    if cand.is_dir():
        return cand
    try:
        subs = [p for p in root.iterdir() if p.is_dir()]
    except Exception:
        return None
    if any(any(p.glob("*.dcm")) or any(p.glob("*/*.dcm")) for p in subs):
        return root
    # 再下一层找 影像
    for p in subs:
        if (p / "影像").is_dir():
            return p / "影像"
    return None


def guess_ct_locations() -> list[Path]:
    """首次使用时自动找几个常见位置，减少用户操作"""
    out = []
    here = app_dir()
    for p in [here, here.parent, here.parent.parent]:
        r = resolve_ct_root(p)
        if r:
            out.append(r)
    # 去重
    seen, uniq = set(), []
    for p in out:
        k = str(p).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


# ============================================================
# 主界面
# ============================================================
class QCApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_config()
        self.cases_dir = MASK_DIR if MASK_DIR is not None else app_dir() / "masks"
        self.info = load_case_info()
        self.results = load_results()
        self.scorer = self.cfg.get("scorer", "") or ""

        self.pids: list[str] = []
        self.cur = 0
        self.vol = None          # (z,y,x) int16
        self.mask = None         # (z,y,x) uint8
        self.z = 0
        self.wl = float(self.cfg.get("wl", 40.0) or 40.0)
        self.ww = float(self.cfg.get("ww", 400.0) or 400.0)
        self.mask_mode = self.cfg.get("mask_mode", "fill")
        if self.mask_mode not in MASK_MODE_ORDER:
            self.mask_mode = "fill"
        self._img_ref = None
        self._busy = False
        self._cur_pid = None

        root.title(f"{APP_TITLE} v{VERSION}")
        root.configure(bg=BG)
        root.minsize(1000, 680)
        self._build_ui()
        self._bind_keys()
        self.set_mask_mode(self.mask_mode, save=False)     # 初始化高亮

        if not self._prepare():
            root.after(200, root.destroy)
            return
        self._build_rows()
        self._load_case(self._resume_index())

    # ---------- 进度记忆 ----------
    def _resume_index(self) -> int:
        """接着上次看到的那一例继续"""
        self._resume_idx = 0
        self._resumed_from = None
        last = self.cfg.get("last_pid")
        if last and last in self.pids:
            self._resume_idx = self.pids.index(last)
            self._resumed_from = last
        return self._resume_idx

    def _save_progress(self):
        """记下当前病例与窗宽窗位，下次打开直接接上"""
        if self._cur_pid:
            self.cfg["last_pid"] = self._cur_pid
        self.cfg["wl"] = round(self.wl, 1)
        self.cfg["ww"] = round(self.ww, 1)
        save_config(self.cfg)

    # ---------- 配置 ----------
    def _prepare(self) -> bool:
        ct_root = str(CT_ROOT) if CT_ROOT is not None else self.cfg.get("ct_root")
        p = Path(ct_root) if ct_root else None
        if not p or not resolve_ct_root(p):
            found = guess_ct_locations()
            if len(found) == 1:
                self.ct_dir = found[0]
            else:
                if not self._ask_ct_dir(found):
                    return False
        else:
            self.ct_dir = resolve_ct_root(p)

        if not self.cases_dir.is_dir():
            selected = filedialog.askdirectory(title="请选择掩膜文件夹（*.nii.gz）")
            if not selected:
                return False
            self.cases_dir = Path(selected)

        # 交集病例
        mask_pids = sorted(p.stem.replace(".nii", "") for p in self.cases_dir.glob("*.nii.gz"))
        ct_pids = {p.name for p in self.ct_dir.iterdir() if p.is_dir()}
        self.pids = [p for p in mask_pids if p in ct_pids]
        self.missing = [p for p in mask_pids if p not in ct_pids]
        if not self.pids:
            messagebox.showerror("找不到病例",
                                 f"CT 目录里没有匹配的病例。\n\nCT 目录：{self.ct_dir}\n"
                                 f"掩膜目录：{self.cases_dir}")
            return False

        if not self.scorer:
            name = simpledialog.askstring("质控人", "请填写您的姓名（结果文件会记录）：",
                                          parent=self.root)
            self.scorer = (name or "").strip() or "未署名"
            self.cfg["scorer"] = self.scorer
            save_config(self.cfg)

        self.cfg["ct_root"] = str(self.ct_dir)
        save_config(self.cfg)
        return True

    def _ask_ct_dir(self, candidates) -> bool:
        msg = ("程序需要先找到 CT 影像所在的位置（只需要设置一次，以后不用再选）。\n\n"
               "请选择包含病例子文件夹的 CT 目录，或其上一级「影像」目录。")
        if candidates:
            msg += "\n\n（程序在以下位置发现了疑似目录，可先点「使用自动找到的」）\n" + \
                   "\n".join(f"· {c}" for c in candidates[:3])
            use_auto = messagebox.askyesno("第一步：找 CT 影像", msg + "\n\n是否使用自动找到的目录？")
            if use_auto:
                self.ct_dir = candidates[0]
                return True
        messagebox.showinfo("第一步：找 CT 影像", msg)
        while True:
            d = filedialog.askdirectory(title="请选择 CT 读片包所在文件夹（含「影像」）")
            if not d:
                return False
            r = resolve_ct_root(Path(d))
            if r:
                self.ct_dir = r
                return True
            if messagebox.askretrycancel("没找到影像", "这个文件夹里没有「影像」子文件夹，请重新选择。"):
                continue
            return False

    # ---------- UI ----------
    def F(self, px, bold=False, mono=False):
        """按 1920 宽屏幕为基准生成像素字号；4K 屏自动放大一倍"""
        fam = "Consolas" if mono else "Microsoft YaHei UI"
        s = max(9, int(px * self.ui))
        return (fam, -s, "bold") if bold else (fam, -s)

    def P(self, n):
        return int(round(n * self.ui))

    def _build_ui(self):
        # 以 1920 宽屏为基准，按实际屏幕宽度整体放大（4K 屏 x2），否则字会小到看不见
        try:
            sw = self.root.winfo_screenwidth()
            self.ui = max(1.0, min(sw / 1920.0, 2.5))
        except Exception:
            self.ui = 1.0
        ui = self.ui

        # 顶栏
        top = tk.Frame(self.root, bg=BG2, height=self.P(64))
        top.pack(side="top", fill="x")
        top.pack_propagate(False)
        self.lb_pid = tk.Label(top, text="—", bg=BG2, fg=FG, font=self.F(26, True))
        self.lb_pid.pack(side="left", padx=(self.P(18), self.P(14)), pady=self.P(10))
        self.lb_meta = tk.Label(top, text="", bg=BG2, fg=FG2, font=self.F(15))
        self.lb_meta.pack(side="left", pady=self.P(10))
        self.lb_flag = tk.Label(top, text="", bg=BG2, fg=C_FLAG, font=self.F(15, True))
        self.lb_flag.pack(side="left", padx=self.P(14))
        self.lb_prog = tk.Label(top, text="", bg=BG2, fg=FG2, font=self.F(15))
        self.lb_prog.pack(side="right", padx=(0, self.P(18)))

        # 顶栏右侧：分割显示方式（填充会遮挡膀胱壁和贴壁病灶，可切“仅轮廓/隐藏”）
        grp = tk.Frame(top, bg=BG2)
        grp.pack(side="right", padx=(0, self.P(20)))
        tk.Label(grp, text="分割显示", bg=BG2, fg=FG2,
                 font=self.F(13)).pack(side="left", padx=(0, self.P(8)))
        self.mask_btns = {}
        for mkey, mlabel in MASK_MODES:
            b = tk.Button(grp, text=mlabel, bg=BG3, fg=FG2, bd=0, font=self.F(13),
                          padx=self.P(11), pady=self.P(3),
                          activebackground="#2c3849", activeforeground=FG,
                          command=lambda k=mkey: self.set_mask_mode(k))
            b.pack(side="left", padx=self.P(3))
            self.mask_btns[mkey] = b

        # 先给底部和顶栏留位置，再让 canvas 占剩余（否则按钮会被挤没）
        bottom = tk.Frame(self.root, bg=BG2)
        self.bottom = bottom
        bottom.pack(side="bottom", fill="x")
        body = tk.Frame(self.root, bg=BG)
        self.body = body
        body.pack(side="top", fill="both", expand=True)

        # 左侧：评分表（病例 / 结论 / 备注），同时充当进度总览
        left = tk.Frame(body, bg=BG2, width=self.P(430))
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        head = tk.Frame(left, bg=BG2)
        head.pack(fill="x", padx=self.P(12), pady=(self.P(8), self.P(6)))
        tk.Label(head, text="评分表", bg=BG2, fg=FG,
                 font=self.F(14, True)).pack(side="left")

        self.lb_stat = tk.Label(left, text="", bg=BG2, fg=FG2, font=self.F(11), anchor="w")
        self.lb_stat.pack(side="bottom", fill="x", padx=self.P(12), pady=(0, self.P(8)))

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("QC.Treeview", background=BG2, fieldbackground=BG2, foreground=FG,
                        rowheight=self.P(30), borderwidth=0, font=self.F(15))
        style.configure("QC.Treeview.Heading", background=BG3, foreground=FG2,
                        font=self.F(13), relief="flat", borderwidth=0,
                        padding=(self.P(4), self.P(4)))
        style.map("QC.Treeview.Heading", background=[("active", "#2c3849")])
        style.map("QC.Treeview",
                  background=[("selected", "#27405e")],
                  foreground=[("selected", "#ffffff")])

        wrap = tk.Frame(left, bg=BG2)
        wrap.pack(fill="both", expand=True, padx=(self.P(8), 0))
        self.tree = ttk.Treeview(wrap, columns=("pid", "grade", "note"), show="headings",
                                 style="QC.Treeview", selectmode="browse")
        self.tree.heading("pid", text="病例", anchor="w")
        self.tree.heading("grade", text="结论", anchor="center")
        self.tree.heading("note", text="备注", anchor="w")
        self.tree.column("pid", width=self.P(168), minwidth=self.P(140), anchor="w", stretch=True)
        self.tree.column("grade", width=self.P(78), minwidth=self.P(70), anchor="center", stretch=False)
        self.tree.column("note", width=self.P(150), minwidth=self.P(60), anchor="w", stretch=True)
        self.tree.tag_configure("none", foreground=FG)
        for _g, _col in GRADE_FG.items():
            self.tree.tag_configure(_g, foreground=_col)
        self.tree.pack(side="left", fill="both", expand=True, pady=(0, self.P(4)))
        _sb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        _sb.pack(side="right", fill="y", pady=(0, self.P(4)))
        self.tree.configure(yscrollcommand=_sb.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self.canvas = tk.Canvas(body, bg="#000000", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.root.after(30, self.draw))
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self.step(-1))
        self.canvas.bind("<Button-5>", lambda e: self.step(1))

        # 第一行：翻层
        row1 = tk.Frame(bottom, bg=BG2)
        row1.pack(fill="x", padx=self.P(14), pady=(self.P(8), self.P(2)))
        self.btn_prev = tk.Button(row1, text="◀ 上一层", command=lambda: self.step(-1),
                                  bg=BG3, fg=FG, bd=0, font=self.F(15),
                                  activebackground="#2c3849", activeforeground=FG,
                                  padx=self.P(10), pady=self.P(3))
        self.btn_prev.pack(side="left")
        self.scale = tk.Scale(row1, from_=0, to=100, orient="horizontal",
                              bg=BG2, fg=FG, troughcolor=BG3, highlightthickness=0,
                              showvalue=False, command=self._on_scale,
                              sliderlength=self.P(26), width=self.P(18), bd=0)
        self.scale.pack(side="left", fill="x", expand=True, padx=self.P(12))
        self.btn_next = tk.Button(row1, text="下一层 ▶", command=lambda: self.step(1),
                                  bg=BG3, fg=FG, bd=0, font=self.F(15),
                                  activebackground="#2c3849", activeforeground=FG,
                                  padx=self.P(10), pady=self.P(3))
        self.btn_next.pack(side="left")
        self.lb_z = tk.Label(row1, text="", bg=BG2, fg=FG2, font=self.F(15, mono=True))
        self.lb_z.pack(side="left", padx=(self.P(12), 0))

        # 第二行：四个结论按钮（做大的，好点）
        row2 = tk.Frame(bottom, bg=BG2)
        row2.pack(fill="x", padx=self.P(14), pady=(self.P(6), self.P(6)))
        self.grade_btns = {}
        for key, label, color, hot in GRADES:
            b = tk.Button(row2, text=f"{label}  （{hot}）", bg=BG3, fg=FG, bd=0,
                          font=self.F(17, True),
                          activebackground=color, activeforeground="#ffffff",
                          padx=self.P(18), pady=self.P(8),
                          command=lambda k=key: self.grade(k))
            b.pack(side="left", padx=(0, self.P(10)))
            self.grade_btns[key] = (b, color)
        self.lb_status = tk.Label(row2, text="", bg=BG2, fg=FG2, font=self.F(13))
        self.lb_status.pack(side="left", padx=self.P(12))

        # 第三行：备注 + 切病例
        row3 = tk.Frame(bottom, bg=BG2)
        row3.pack(fill="x", padx=self.P(14), pady=(0, self.P(8)))
        tk.Label(row3, text="备注：", bg=BG2, fg=FG2, font=self.F(14)).pack(side="left")
        self.ent_note = tk.Entry(row3, bg=BG, fg=FG, insertbackground=FG, bd=0,
                                 font=self.F(15))
        self.ent_note.pack(side="left", fill="x", expand=True, padx=(0, self.P(10)),
                           ipady=self.P(6))
        tk.Button(row3, text="上一例 ←", command=lambda: self.goto(self.cur - 1),
                  bg=BG3, fg=FG, bd=0, font=self.F(14), padx=self.P(10),
                  pady=self.P(3)).pack(side="left", padx=self.P(4))
        tk.Button(row3, text="下一例 →", command=lambda: self.goto(self.cur + 1),
                  bg=BG3, fg=FG, bd=0, font=self.F(14), padx=self.P(10),
                  pady=self.P(3)).pack(side="left", padx=self.P(4))

        self.lb_hint = tk.Label(bottom, bg=BG2, fg="#6b7688", font=self.F(13),
                                text="滚轮 / ↑↓ 翻层　·　PgUp PgDn 跳 10 层　·　右键拖动 调窗宽窗位"
                                     "　·　M 切换分割显示（填充/仅轮廓/隐藏）　·　1~4 打分"
                                     "　·　← → 换病例　·　空格 下一例未评")
        self.lb_hint.pack(fill="x", padx=self.P(14), pady=(0, self.P(6)))


    def _bind_keys(self):
        r = self.root
        r.bind("<Up>", lambda e: self.step(-1))
        r.bind("<Down>", lambda e: self.step(1))
        r.bind("<Prior>", lambda e: self.step(-10))
        r.bind("<Next>", lambda e: self.step(10))
        r.bind("<Left>", lambda e: self.goto(self.cur - 1))
        r.bind("<Right>", lambda e: self.goto(self.cur + 1))
        r.bind("<space>", self._on_space)
        for key, hot in [("pass", "1"), ("minor", "2"), ("fail", "3"), ("exclude", "4")]:
            r.bind(hot, lambda e, k=key: self._hot(k))
        for ch in ("m", "M"):
            r.bind(ch, self._hot_mask)
        self.canvas.bind("<ButtonPress-3>", self._win_start)
        self.canvas.bind("<B3-Motion>", self._win_drag)
        self.canvas.bind("<ButtonRelease-3>", lambda e: self._save_progress())
        self.canvas.bind("<ButtonPress-1>", self._drag_start)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)

    # ---------- 鼠标窗宽窗位 / 平移 ----------
    def _win_start(self, e):
        self._w0 = (e.x, e.y, self.wl, self.ww)

    def _win_drag(self, e):
        if not hasattr(self, "_w0"):
            return
        x0, y0, wl0, ww0 = self._w0
        self.ww = float(np.clip(ww0 + (e.x - x0) * 3, 100, 3000))
        self.wl = float(np.clip(wl0 - (e.y - y0) * 2, -400, 900))
        self.draw()

    def _drag_start(self, e):
        self._d0 = (e.x, e.y)

    def _drag_move(self, e):
        pass

    def _drag_end(self, e):
        pass

    # ---------- 评分表（左侧） ----------
    def _upsert_row(self, pid: str):
        r = self.results.get(pid, {})
        g = r.get("grade", "")
        label = GRADE_LABEL.get(g, "")
        note = (r.get("note") or "").replace("\n", " ").strip()
        if len(note) > 13:
            note = note[:13] + "…"
        vals = (pid, ("● " + label) if label else "", note)
        tag = g if g in GRADE_LABEL else "none"
        if self.tree.exists(pid):
            self.tree.item(pid, values=vals, tags=(tag,))
        else:
            self.tree.insert("", "end", iid=pid, values=vals, tags=(tag,))

    def _build_rows(self):
        for pid in self.pids:
            self._upsert_row(pid)
        self._update_stat()

    def _update_stat(self):
        cnt = {k: 0 for k in GRADE_LABEL}
        for pid in self.pids:
            g = self.results.get(pid, {}).get("grade")
            if g in cnt:
                cnt[g] += 1
        done = sum(cnt.values())
        self.lb_stat.config(
            text=f"{done}/{len(self.pids)} 评完 · 通{cnt['pass']} 轻{cnt['minor']}"
                 f" 失{cnt['fail']} 排{cnt['exclude']}")
        txt = f"已评 {done} / {len(self.pids)}"
        if getattr(self, "missing", None):
            txt += f"（CT 目录缺 {len(self.missing)} 例）"
        self.lb_prog.config(text=txt)

    def _refresh_list(self):
        for pid in self.pids:
            self._upsert_row(pid)
        self._update_stat()

    def _select_in_tree(self, pid: str):
        if not self.tree.exists(pid):
            return
        self.tree.selection_set(pid)
        self.tree.see(pid)

    def _on_select(self, _=None):
        sel = self.tree.selection()
        if not sel:
            return
        pid = sel[0]
        if self._busy or pid == self._cur_pid:
            return
        if pid in self.pids:
            self.goto(self.pids.index(pid))

    # ---------- 加载病例 ----------
    def _set_buttons_enabled(self, on: bool):
        for _k, (b, _c) in self.grade_btns.items():
            b.config(state="normal" if on else "disabled")

    def _load_case(self, idx: int):
        if not (0 <= idx < len(self.pids)):
            return
        # 先把上一例的大数组放掉：否则新数组分配期间新旧两份并存，
        # 峰值会多出一个整例（本批最大约 350 MB）
        self.vol = None
        self.mask = None
        self._img_ref = None
        gc.collect()

        self.cur = idx
        pid = self.pids[idx]
        self._cur_pid = pid
        self._busy = True
        self._set_buttons_enabled(False)     # 读取期间禁止打分，避免记到错病例上
        self._status(f"正在读取 {pid} 的 CT …")
        self.root.update_idletasks()

        t0 = time.time()
        try:
            case_dir = self.ct_dir / pid
            sub = [p for p in case_dir.iterdir() if p.is_dir()]
            if len(sub) > 1:
                raise ValueError("病例包含多个序列目录，请仅保留需要质控的一个序列目录")
            sdir = sub[0] if sub else case_dir
            mask_path = self.cases_dir / f"{pid}.nii.gz"
            # 先读掩膜：拿到层数和 z 方向，才能决定 DICOM 怎么排序/去重
            mask, _, mask_meta = read_nifti_gz(mask_path)
            vol, spacing = load_dicom_series(
                sdir, expect_n=mask.shape[0], z_sign=mask_meta["dz"],
                z0=mask_meta.get("z0"), progress=lambda m: self._status(m),
                mask_geometry=mask_meta)
            if mask.shape != vol.shape:
                # 层数实在对不上：不硬报错，改为只显示 CT 并提示，医生可以判“该例排除”后继续
                self._mask_mismatch = f"分割 {mask.shape[0]} 层 / 影像 {vol.shape[0]} 层"
                mask = None
            else:
                self._mask_mismatch = None
        except Exception as ex:
            # 关键：失败时必须清空影像，否则界面上还是上一例的图，
            # 医生可能对着旧图给新病例打分
            self.vol = None
            self.mask = None
            self._cur_pid = None
            self._busy = False
            self._set_buttons_enabled(True)
            self.canvas.delete("all")
            self.lb_pid.config(text=pid + "（读取失败）")
            self.lb_meta.config(text=str(ex)[:120])
            self.lb_flag.config(text="")
            self._status("读取失败，可重试或跳到下一例")
            messagebox.showerror("读取失败", f"{pid}\n\n{ex}")
            return

        # 掩膜本来就是 uint8 0/1 时跳过 (m>0).astype，省掉一份 174 MB 的临时数组
        self.vol = vol
        if mask is not None:
            if mask.dtype != np.uint8 or int(mask.max(initial=0)) > 1:
                mask = (mask > 0).astype(np.uint8)
            self.mask = mask
        else:
            self.mask = None
        nz = vol.shape[0]
        self.scale.config(from_=0, to=nz - 1)
        # 默认停在分割的首层偏上，便于直接看到轮廓
        if self.mask is not None:
            # 默认停在分割面积最大的那一层：一打开就能看到最大的膀胱截面，
            # 比停在首层附近（边缘常常只有几十个体素）直观得多
            counts = self.mask.reshape(nz, -1).sum(axis=1)
            self.z = int(counts.argmax()) if counts.max() > 0 else nz // 2
        else:
            self.z = nz // 2
        self.scale.set(self.z)
        self._update_head(pid, spacing)
        self._upsert_row(pid)
        self._update_stat()
        self._select_in_tree(pid)
        self._fill_result_fields()
        self._busy = False
        self._set_buttons_enabled(True)
        self._save_progress()
        msg = f"已加载（{time.time()-t0:.1f} 秒）"
        if getattr(self, "_resumed_from", None) and idx == self._resume_idx:
            msg += "　·　已接着上次的进度"
            self._resumed_from = None
        self._status(msg)
        self.root.after(50, self.draw)

    def _update_head(self, pid, spacing):
        info = self.info.get(pid, {})
        vol_ml = info.get("volume_ml")
        txt = ""
        if vol_ml is not None:
            txt = f"自动分割体积 {vol_ml:.1f} mL"
        if info.get("vis") is not None:
            txt += f"   ·   读片可见性 {info['vis']}"
        if info.get("track2"):
            txt += f"   ·   主分析轨 {info['track2']}"
        self.lb_pid.config(text=pid)
        self.lb_meta.config(text=txt)
        mm = getattr(self, "_mask_mismatch", None)
        if mm:
            self.lb_flag.config(
                text=f"⚠ 分割与影像层数不符（{mm}），无法叠加 → 建议记「该例排除」")
            return
        flags = info.get("flags") or ""
        self.lb_flag.config(text=("⚠ " + flags.replace(";", "  ⚠ ")) if flags else "")

    def _status(self, msg):
        self.lb_status.config(text=msg)
        if not self._busy:
            self.lb_status.config(fg=FG2)
        self.root.update_idletasks()

    # ---------- 绘制 ----------
    def draw(self, cw=None, ch=None):
        if self.vol is None or self._busy:
            return
        if cw is None:
            cw = self.canvas.winfo_width()
        if ch is None:
            ch = self.canvas.winfo_height()
        if cw < 200 or ch < 200:      # 布局还没完成，等 <Configure> 再画
            return
        z = int(np.clip(self.z, 0, self.vol.shape[0] - 1))
        arr = self.vol[z]
        lo = self.wl - self.ww / 2.0
        hi = self.wl + self.ww / 2.0
        img = np.clip((arr.astype(np.float32) - lo) * (255.0 / (hi - lo)), 0, 255).astype(np.uint8)
        rgb = np.repeat(img[:, :, None], 3, axis=2)

        # 必须显式转 bool：uint8 会被 numpy 当整数索引。
        # mask 为 None 表示这一例分割与影像层数对不上，只显示 CT
        m = self.mask[z].astype(bool) if self.mask is not None else None
        if m is not None and m.any() and self.mask_mode != "off":
            if self.mask_mode == "fill":
                # 半透明橙红填充：看得见整体范围，但会压暗膀胱壁细节
                col = np.array([255, 92, 40], np.float32)
                rgb[m] = (rgb[m].astype(np.float32) * 0.58 + col * 0.42).astype(np.uint8)

            # 4 邻域边缘 = 轮廓线
            er = m.copy()
            er[1:, :] &= m[:-1, :]
            er[:-1, :] &= m[1:, :]
            er[:, 1:] &= m[:, :-1]
            er[:, :-1] &= m[:, 1:]
            edge = m & ~er
            if self.mask_mode == "outline":
                # 仅轮廓模式：线加粗到 2 像素，只描边、不遮挡任何像素
                e2 = edge.copy()
                e2[1:, :] |= edge[:-1, :]
                e2[:-1, :] |= edge[1:, :]
                e2[:, 1:] |= edge[:, :-1]
                e2[:, :-1] |= edge[:, 1:]
                edge = e2
            rgb[edge] = (255, 214, 0)

        pil = Image.fromarray(rgb)          # 已是 uint8 RGB，无需 mode=
        w, h = pil.size
        k = min(cw / w, ch / h)
        if k != 1.0:
            pil = pil.resize((max(1, int(w * k)), max(1, int(h * k))), Image.BILINEAR)
        self._img_ref = ImageTk.PhotoImage(pil)
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=self._img_ref, anchor="center")
        self.lb_z.config(text=f"第 {z+1}/{self.vol.shape[0]} 层")
        self.scale.set(z)

    def step(self, d):
        if self.vol is None:
            return
        self.z = int(np.clip(self.z + d, 0, self.vol.shape[0] - 1))
        self.draw()

    def _on_wheel(self, e):
        self.step(-1 if e.delta > 0 else 1)

    def _on_scale(self, v):
        if self._busy or self.vol is None:
            return
        z = int(float(v))
        if z != self.z:
            self.z = z
            self.draw()

    # ---------- 病例切换 ----------
    def goto(self, idx):
        if not self.pids or self._busy:      # 正在读片时忽略翻页，避免排队/错配
            return
        if idx < 0:
            self._status("已经是第一例了")
            return
        if idx >= len(self.pids):
            done = sum(1 for p in self.pids if self.results.get(p, {}).get("grade"))
            if done >= len(self.pids):
                messagebox.showinfo("完成", f"{len(self.pids)} 例已全部评完。\n\n请交回输出目录下的「质控结果.csv」。")
            else:
                self._status(f"已经是最后一例了（还有 {len(self.pids) - done} 例未评）")
            return
        if idx != self.cur:
            if not self._save_note():
                return
            self._load_case(idx)

    # ---------- 打分 ----------
    def _hot(self, key):
        if isinstance(self.root.focus_get(), (tk.Entry, tk.Text)):
            return
        self.grade(key)

    def grade(self, key):
        if self._busy or self.vol is None or self._cur_pid is None:
            return
        pid = self._cur_pid
        note = self.ent_note.get().strip()
        self.results[pid] = {
            "patient_id": pid,
            "grade": key,
            "note": note,
            "scorer": self.scorer,
            "time": time.strftime("%Y-%m-%d %H:%M"),
        }
        self._results_dirty = True
        if not save_results(self.results):
            self._status("结果尚未保存，请解除文件占用或检查目录写入权限后重试")
            return
        self._results_dirty = False
        self._upsert_row(pid)
        self._update_stat()
        self._highlight_grade(key)
        self._status({"pass": "已标记：通过", "minor": "已标记：轻微问题",
                      "fail": "已标记：失败需重做", "exclude": "已标记：该例排除"}.get(key, "已标记")
                     + "　→ 按 → 或「下一例」继续")

    def _highlight_grade(self, key):
        for k, (b, color) in self.grade_btns.items():
            if k == key:
                b.config(bg=color, fg="#ffffff")
            else:
                b.config(bg=BG3, fg=FG)

    def _fill_result_fields(self):
        r = self.results.get(self._cur_pid, {})
        self.ent_note.delete(0, "end")
        self.ent_note.insert(0, r.get("note", ""))
        self._highlight_grade(r.get("grade"))

    def _save_note(self):
        if self._cur_pid and self._cur_pid in self.results:
            note = self.ent_note.get().strip()
            if self.results[self._cur_pid].get("note", "") != note:
                self.results[self._cur_pid]["note"] = note
                self._results_dirty = True
        if getattr(self, "_results_dirty", False):
            if not save_results(self.results):
                self._status("结果尚未保存，已阻止切换或关闭；请处理文件占用或写入权限后重试")
                return False
            self._results_dirty = False
            if self._cur_pid:
                self._upsert_row(self._cur_pid)
        return True

    # ---------- 分割显示方式（填充 / 仅轮廓 / 隐藏） ----------
    def set_mask_mode(self, mode, save=True):
        if mode not in MASK_MODE_ORDER:
            return
        self.mask_mode = mode
        for k, b in self.mask_btns.items():
            if k == mode:
                b.config(bg=ACCENT, fg="#08101c")
            else:
                b.config(bg=BG3, fg=FG2)
        if save:
            self.cfg["mask_mode"] = mode
            save_config(self.cfg)
        self.draw()

    def cycle_mask_mode(self):
        i = MASK_MODE_ORDER.index(self.mask_mode)
        self.set_mask_mode(MASK_MODE_ORDER[(i + 1) % len(MASK_MODE_ORDER)])

    def _hot_mask(self, e=None):
        if isinstance(self.root.focus_get(), (tk.Entry, tk.Text)):
            return
        self.cycle_mask_mode()

    def _on_space(self, e=None):
        if not self._save_note():
            return
        start = self.cur + 1
        for i in list(range(start, len(self.pids))) + list(range(0, start)):
            if not self.results.get(self.pids[i], {}).get("grade"):
                self.goto(i)
                return
        messagebox.showinfo("完成", "所有病例都已评完。\n\n请把程序目录下的「质控结果.csv」发回。")

    def on_close(self):
        if not self._save_note():
            return
        self._save_progress()
        for callback in self.root.tk.call("after", "info"):
            self.root.after_cancel(callback)
        self.root.destroy()


# ============================================================
# 配置与结果文件
# ============================================================
def load_config() -> dict:
    p = data_dir() / "设置.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_config(cfg: dict):
    try:
        (data_dir() / "设置.json").write_text(
            json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_case_info() -> dict:
    p = app_dir() / "病例信息.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


RESULT_COLS = ["patient_id", "grade", "note", "scorer", "time"]
_RESULTS_READ_FAILED = None


def load_results() -> dict:
    global _RESULTS_READ_FAILED
    p = data_dir() / "质控结果.csv"
    out = {}
    if not p.exists():
        return out
    try:
        with open(p, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, strict=True)
            if reader.fieldnames is None or sorted(reader.fieldnames) != sorted(RESULT_COLS):
                raise ValueError("CSV 列名不完整或不受支持")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"CSV 第 {reader.line_num} 行列数不正确")
                pid = row["patient_id"]
                if not pid or pid in out:
                    raise ValueError(f"CSV 第 {reader.line_num} 行病例编号为空或重复")
                if row["grade"] not in {"", *GRADE_LABEL}:
                    raise ValueError(f"CSV 第 {reader.line_num} 行评分无效")
                out[pid] = row
    except Exception as ex:
        _RESULTS_READ_FAILED = p.resolve()
        raise ValueError(f"无法完整读取已有结果，已禁止覆盖：{p}\n{ex}") from ex
    _RESULTS_READ_FAILED = None
    return out


def save_results(res: dict) -> bool:
    """写回 质控结果.csv（原子替换）。失败必须让医生看到，否则他以为存了。"""
    p = data_dir() / "质控结果.csv"
    tmp = p.with_suffix(".tmp")
    try:
        if _RESULTS_READ_FAILED == p.resolve():
            raise ValueError("已有结果读取失败，已禁止覆盖；请先备份并修复 CSV，然后重启程序")
        with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=RESULT_COLS)
            w.writeheader()
            for pid in sorted(res):
                r = res[pid]
                w.writerow({k: r.get(k, "") for k in RESULT_COLS})
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
        return True
    except Exception as ex:
        try:
            messagebox.showerror(
                "结果没能保存",
                f"写入「质控结果.csv」失败：\n{ex}\n\n"
                "已评内容仍在内存里，程序会阻止切换或关闭。\n"
                "请解除文件占用或检查目录写入权限，然后重试。")
        except Exception:
            pass
        return False


def _setup_tcl():
    """打包成 exe 后，告诉 Tk 去哪里找 tcl/tk 的运行库"""
    if not getattr(sys, "frozen", False):
        return
    base = Path(getattr(sys, "_MEIPASS", app_dir()))
    for env, sub in (("TCL_LIBRARY", "_tcl_data"), ("TK_LIBRARY", "_tk_data")):
        p = base / sub
        if p.is_dir():
            os.environ[env] = str(p)


def main():
    global OUTPUT_DIR, CT_ROOT, MASK_DIR
    parser = argparse.ArgumentParser(description="CT segmentation quality-control viewer")
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--ct-root", type=Path)
    parser.add_argument("--mask-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--mask-mode", choices=MASK_MODE_ORDER)
    parser.add_argument("--shot", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--demo-grade", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    OUTPUT_DIR = args.output_dir.resolve() if args.output_dir else None
    CT_ROOT = args.ct_root.resolve() if args.ct_root else None
    MASK_DIR = args.mask_dir.resolve() if args.mask_dir else None
    data_dir().mkdir(parents=True, exist_ok=True)
    _setup_tcl()
    # 不主动声明 DPI 感知：交给 Windows 统一缩放，Tk 内部坐标才与显示一致
    root = tk.Tk()
    try:
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{sw}x{max(sh - 70, 600)}+0+0")   # 留出任务栏，医生不用调窗口
    except Exception:
        pass
    try:
        root.tk.call("tk", "scaling", 1.0)
    except Exception:
        pass
    try:
        app = QCApp(root)
    except (ValueError, OSError) as ex:
        messagebox.showerror("无法读取质控记录", str(ex))
        root.destroy()
        return
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    for i, a in enumerate(sys.argv):        # 开发用：--mask-mode outline / off
        if a == "--mask-mode" and i + 1 < len(sys.argv):
            app.set_mask_mode(sys.argv[i + 1], save=False)
    if "_PYI_SPLASH_IPC" in os.environ:    # 关掉启动画面（没打 splash 时跳过，避免无谓报错）
        try:
            import pyi_splash
            pyi_splash.close()
        except Exception:
            pass

    shot = None
    for i, a in enumerate(sys.argv):
        if a == "--shot" and i + 1 < len(sys.argv):
            shot = sys.argv[i + 1]
    if shot:
        def _grab():
            try:
                from PIL import ImageGrab
                full = ImageGrab.grab(all_screens=True)
                kx = full.width / max(root.winfo_screenwidth(), 1)
                ky = full.height / max(root.winfo_screenheight(), 1)
                x, y = root.winfo_rootx(), root.winfo_rooty()
                w, h = root.winfo_width(), root.winfo_height()
                full.crop((int(x * kx), int(y * ky),
                           int((x + w) * kx), int((y + h) * ky))).save(shot)
            except Exception as ex:
                print("shot failed", ex)
            root.destroy()

        def _snap():
            root.attributes("-topmost", True)
            root.lift()
            root.focus_force()
            root.update()
            if "--demo-grade" in sys.argv:
                app.ent_note.insert(0, "测试备注：上极略欠")
                app.grade("minor")
            root.after(700, _grab)

        root.after(6000, _snap)

    root.mainloop()


if __name__ == "__main__":
    main()
