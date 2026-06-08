#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, subprocess, math, threading, json, ctypes, base64
from pathlib import Path
from datetime import datetime, timezone
from ctypes import wintypes

# ── 依赖安装 ──────────────────────────────────────────────
for _pkg, _imp in [("requests", "requests"), ("Pillow", "PIL")]:
    try:
        __import__(_imp)
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", _pkg, "-q", "--break-system-packages"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

import requests
import tkinter as tk
import tkinter.font as tkfont
from PIL import Image, ImageDraw, ImageTk

# PyInstaller 打包后 __file__ 指向 exe，资源文件在 sys._MEIPASS；
# 配置文件写在 exe 同目录，便于用户保留认证信息。
if getattr(sys, "frozen", False):
    _BASE_RES = Path(sys._MEIPASS)
    _BASE_CFG = Path(sys.executable).parent
else:
    _BASE_RES = Path(__file__).parent
    _BASE_CFG = Path(__file__).parent

CONFIG_FILE = _BASE_CFG / "claude_widget_config.json"
# 资源目录策略：
# - 图标（界面 PNG）→ 始终从打包内读，不开放替换
# - 桌宠 GIF / 提示音 → 从 exe 同目录的 asset/ 读，让朋友能直接拖文件替换；
#   首次运行 exe 时自动把打包内的默认素材 seed 到 exe 旁，之后再不覆盖用户文件。
ASSET_DIR_BUNDLED = _BASE_RES / "asset"     # 打包内（_MEIPASS 或开发态项目根）
ASSET_DIR_USER    = _BASE_CFG / "asset"     # exe 同目录（开发态等同 bundled）
ICON_DIR    = ASSET_DIR_BUNDLED / "icon"
SOUND_DIR   = ASSET_DIR_USER    / "sound"
MASCOT_DIR  = ASSET_DIR_USER    / "gif"
# 桌宠 GIF：优先 cfg.mascot_file（用户选定），
# 找不到回退到 MASCOT_PRIMARY_NAME，再不行用 asset/gif/ 下任意 .gif（按文件名排序）。
MASCOT_PRIMARY_NAME = "u_mey4kjj5ww-angry-2498.gif"
DONE_SOUND_DEFAULT  = "dragon-studio-new-notification-3-398649.mp3"
RESET_SOUND_DEFAULT = "universfield-new-notification-09-352705.mp3"
# 桌宠缩放范围（相对 MASCOT_BBOX_W/H）
MASCOT_SCALE_MIN    = 0.4
MASCOT_SCALE_MAX    = 3.0
# 桌宠右上角缩放热区大小（像素）
MASCOT_RESIZE_HIT   = 16


def _seed_user_assets():
    """首次运行 exe 时，把打包内的默认 GIF / 提示音复制到 exe 同目录的 asset/ 下，
    方便朋友直接拖入自己喜欢的素材替换 / 增加 / 删除。
    - 仅 frozen 模式下执行（开发态 user 与 bundled 是同一个文件夹）
    - 仅当目标子目录"不存在"时复制（已存在就尊重用户管理，绝不覆盖）"""
    if not getattr(sys, "frozen", False):
        return
    if ASSET_DIR_BUNDLED == ASSET_DIR_USER:
        return
    import shutil
    for sub in ("gif", "sound"):
        src = ASSET_DIR_BUNDLED / sub
        dst = ASSET_DIR_USER    / sub
        if not src.exists():
            continue
        if dst.exists():
            continue
        try:
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                if f.is_file():
                    try: shutil.copy2(f, dst / f.name)
                    except Exception: pass
        except Exception:
            pass


_seed_user_assets()
# Claude Code Stop hook 写入此 flag 触发 done 提示音
DONE_FLAG   = _BASE_CFG / "temp" / "claude_done.flag"

# 桌宠窗口：100×100 正方形 bbox；默认贴主窗外部右上角并向下偏移 3 像素
MASCOT_BBOX_W     = 100
MASCOT_BBOX_H     = 100
MASCOT_Y_OFFSET   = 3
ANIM_FRAME_MS     = 90
DONE_POLL_MS      = 800   # done flag 文件轮询间隔


# ── 凭证加密（Windows DPAPI）─────────────────────────────
# session_key / org_id 这两个敏感字段在磁盘上以 DPAPI 加密形态存储
# （key 名分别为 session_key_enc / org_id_enc），密文绑定到当前 Windows
# 用户账户：他人拷走 json 也无法解出明文。其它 UI 字段维持明文方便手改。
#
# 内存里的 cfg 字典依旧保留明文 session_key / org_id，因此调用方代码
# （fetch_usage、设置对话框等）一行都不用改。

_SECRET_FIELDS = ("session_key", "org_id")


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _dpapi_encrypt(plaintext: str) -> str:
    """用 Windows DPAPI 加密字符串，返回 base64 文本。失败时抛异常。"""
    if not plaintext:
        return ""
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    data = plaintext.encode("utf-8")
    blob_in = _DATA_BLOB(len(data),
                         ctypes.cast(ctypes.c_char_p(data),
                                     ctypes.POINTER(ctypes.c_byte)))
    blob_out = _DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(blob_in), None, None,
                                    None, None, 0, ctypes.byref(blob_out)):
        raise OSError("CryptProtectData failed")
    try:
        cipher = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)
    return base64.b64encode(cipher).decode("ascii")


def _dpapi_decrypt(b64: str) -> str:
    """解密 _dpapi_encrypt 产物，返回原文。失败时抛异常。"""
    if not b64:
        return ""
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    raw = base64.b64decode(b64.encode("ascii"))
    blob_in = _DATA_BLOB(len(raw),
                         ctypes.cast(ctypes.c_char_p(raw),
                                     ctypes.POINTER(ctypes.c_byte)))
    blob_out = _DATA_BLOB()
    if not crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None,
                                      None, None, 0, ctypes.byref(blob_out)):
        raise OSError("CryptUnprotectData failed")
    try:
        plain = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)
    return plain.decode("utf-8")


def load_cfg():
    """读取 claude_widget_config.json 配置（session_key / org_id / refresh_min 等）。

    磁盘上敏感字段以 *_enc 形式存储（DPAPI 密文 + base64），读出后解密成
    明文放进内存字典；若发现旧版明文字段，则自动迁移加密一次。"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        cfg = json.loads(CONFIG_FILE.read_text("utf-8"))
    except Exception:
        return {}

    migrated = False
    for k in _SECRET_FIELDS:
        enc_k = k + "_enc"
        # 1) 已是密文：解出明文放进内存
        if enc_k in cfg:
            try:
                cfg[k] = _dpapi_decrypt(cfg.pop(enc_k))
            except Exception:
                # 解密失败（如换了 Windows 账户）：清掉，等用户重填
                cfg.pop(enc_k, None)
                cfg[k] = ""
        # 2) 旧版明文：迁移加密
        elif k in cfg and cfg[k]:
            migrated = True

    if migrated:
        try:
            save_cfg(cfg)  # save_cfg 会把明文加密后写盘
        except Exception:
            pass
    return cfg


def save_cfg(c):
    """把配置字典写回 claude_widget_config.json。

    敏感字段写盘前用 DPAPI 加密成 *_enc，明文键不落盘。"""
    out = dict(c)  # 浅拷贝，避免修改调用方持有的内存字典
    for k in _SECRET_FIELDS:
        enc_k = k + "_enc"
        val = out.pop(k, None)
        out.pop(enc_k, None)  # 清掉可能残留的旧密文键
        if val:
            try:
                out[enc_k] = _dpapi_encrypt(val)
            except Exception:
                # 加密失败时退回明文，保功能不丢凭证（极少见）
                out[k] = val
    CONFIG_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), "utf-8")


# ── 颜色 ─────────────────────────────────────────────────
BG            = "#4B4D52"   # 透明色键，勿改
PANEL         = "#111827"   # 面板，主面板背景色
BORDER        = "#1f2d45"   # 文本框描边颜色
TRACK         = "#1e293b"   # 轨道，环形底色
GREEN         = "#22d3a5"
YELLOW        = "#D97757"   # Claude 品牌色
RED           = "#ef4444"
WHITE         = "#ffffff"
MUTED         = "#94a3b8"
ENTRY         = "#0d1117"


def _rgba(hex_c):
    """把 #RRGGBB 颜色字符串转成 PIL 用的 (R, G, B, 255) 元组。"""
    h = hex_c.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 255)


def ring_color(pct):
    """按使用率返回环形配色：<50% 绿、<75% 黄、否则红。"""
    if pct < 0.50: return GREEN
    if pct < 0.75: return YELLOW
    return RED


# ── 尺寸 ─────────────────────────────────────────────────
SCALE      = 3              # PIL 超采样
RO         = 60             # 环外半径
RO_GAP     = 20             # 环外边距
TRACK_W    = 10             # 轨道宽
RI         = RO - TRACK_W   # 环内半径
MID_R      = (RO + RI) / 2  # 圆轨迹
DOT_R      = TRACK_W / 2    # 圆点半径
CX1        = RO + RO_GAP    # 左环圆心 X；右环圆心 = W - CX1
ICON_GAP   = 6              # ICON 间距
ICON_SZ    = 14             # ICON 大小
CY         = CX1 + ICON_SZ
ACCOUNT_BG_ANIM_STEPS    = 14
ACCOUNT_PANEL_ANIM_STEPS = 14
ACCOUNT_ANIM_MS          = 11
ACCOUNT_PANEL_ALPHA      = 0.80  # 面板背景层透明度
W, H       = RO * 4 + RO_GAP * 3, RO * 2 + RO_GAP * 3
AC_EYE_SZ  = 16
AC_INFO_SZ = 12

# 5-hour 用尽时的覆盖圆层透明度
OVERLAY_ALPHA = 0.80

# 紧凑模式：双击主窗体缩到屏幕右边，仅显示 5-hour 环
# 面板收缩到环外圈（圆形面板，仅留 COMPACT_PAD 像素小间距），文字额外放大 20%
COMPACT_SCALE      = 0.5
COMPACT_PAD        = 2
COMPACT_W          = int(RO * 2 * COMPACT_SCALE) + COMPACT_PAD * 2   # 64
COMPACT_H          = COMPACT_W                                       # 正方形，圆形面板
COMPACT_TEXT_SCALE = 1.2   # 紧凑模式下文字额外放大 20%

# 刷新频率：默认/上下限/低频警告阈值（分钟）
REFRESH_MIN_DEFAULT = 5
REFRESH_MIN_MIN     = 1
REFRESH_MIN_MAX     = 30
REFRESH_MIN_WARN    = 3


# ── API ──────────────────────────────────────────────────
def fetch_usage(sk, oid):
    """调用 claude.ai usage API，返回原始 JSON（含 five_hour / seven_day）。"""
    h = {
        "Cookie": f"sessionKey={sk}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Referer": "https://claude.ai/settings/usage",
        "Anthropic-Client-Platform": "web_claude_ai",
        "Anthropic-Client-Version": "1.0.0",
    }
    r = requests.get(
        f"https://claude.ai/api/organizations/{oid}/usage", headers=h, timeout=12
    )
    r.raise_for_status()
    return r.json()


def parse(raw):
    """把 usage 原始 JSON 拆成 5h / 7d 两个环要用的字段（含 reset_at 原始 datetime）。"""
    def _pct(v):
        """把后端百分比 (0-100) 归一化到 0-1 小数；None 时返回 None。"""
        return float(v) / 100.0 if v is not None else None

    def _reset_at(iso):
        """把 ISO 重置时间转成 aware datetime；失败返回 None。"""
        if not iso:
            return None
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except:
            return None

    def _reset(iso):
        """把 ISO 重置时间转成 "Xh YYm" 倒计时字符串，已过期则返回 "即将重置"。"""
        dt = _reset_at(iso)
        if dt is None:
            return ""
        sec = int((dt - datetime.now(timezone.utc)).total_seconds())
        if sec <= 0:
            return "即将重置"
        h, r = divmod(sec, 3600)
        m = r // 60
        return f"{h}h {m:02d}m" if h else f"{m}m"

    fh = raw.get("five_hour") or {}
    sd = raw.get("seven_day") or {}
    return {
        "five_pct":       _pct(fh.get("utilization")),
        "five_reset":     _reset(fh.get("resets_at")),
        "five_reset_at":  _reset_at(fh.get("resets_at")),
        "seven_pct":      _pct(sd.get("utilization")),
        "seven_reset":    _reset(sd.get("resets_at")),
        "seven_reset_at": _reset_at(sd.get("resets_at")),
    }


# ── Tooltip ──────────────────────────────────────────────
class ToolTip:
    """鼠标悬停提示框（ACCOUNT 面板的 ⓘ 图标用）。"""

    def __init__(self, widget, text):
        """绑定 widget 的 Enter / Leave 事件，悬停时展示 text。"""
        self.widget = widget
        self.text   = text
        self.tip    = None
        widget.bind("<Enter>",   self._show)
        widget.bind("<Leave>",   self._hide)
        widget.bind("<Destroy>", lambda e: self._hide(None))

    def _show(self, event):
        """鼠标进入时弹出提示 Toplevel。"""
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 24
        y = self.widget.winfo_rooty() + 20
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        self.tip.wm_attributes("-topmost", True)
        outer = tk.Frame(self.tip, bg=BORDER, bd=0, padx=1, pady=1)
        outer.pack()
        tk.Label(
            outer, text=self.text, bg="#1a2332", fg=WHITE,
            font=("Segoe UI", 8), wraplength=250,
            justify="left", padx=10, pady=7,
        ).pack()

    def _hide(self, event):
        """鼠标离开/控件销毁时关掉提示 Toplevel。"""
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ── PIL 渲染 ──────────────────────────────────────────────
def _render_compact_bg(total_w, h, five_pct, five_overlay, scale):
    """紧凑模式专用渲染：整张画布充满 PANEL 色（实心方块，无透明边缘）→ 避免
    -transparentcolor 在抗锯齿边缘上 keying 出杂色；环用超采样 + LANCZOS 渲染，
    弧形边缘与 PANEL 底色混合得到完全不透明的平滑像素，无锯齿无杂色。"""
    S    = SCALE
    # 整张画布用 PANEL 色填充：没有任何透明像素 → 没有 keying 边缘伪影
    img  = Image.new("RGBA", (total_w * S, h * S), _rgba(PANEL))
    draw = ImageDraw.Draw(img)

    cx  = total_w * S / 2
    cy  = h * S / 2
    sro = RO * scale * S
    sri = RI * scale * S
    stw = max(1, int(round(TRACK_W * scale * S)))
    smr = (sro + sri) / 2
    sdr = stw / 2

    draw.arc(
        [(cx - sro, cy - sro), (cx + sro, cy + sro)],
        start=0, end=359.9, fill=_rgba(TRACK), width=stw,
    )
    if five_pct and five_pct > 0.005:
        col   = ring_color(five_pct)
        sweep = min(five_pct, 1.0) * 360
        draw.arc(
            [(cx - sro, cy - sro), (cx + sro, cy + sro)],
            start=-90, end=-90 + sweep, fill=_rgba(col), width=stw,
        )
        ang   = math.radians(-90 + sweep)
        dot_x = cx + smr * math.cos(ang)
        dot_y = cy + smr * math.sin(ang)
        draw.ellipse(
            [(dot_x - sdr, dot_y - sdr), (dot_x + sdr, dot_y + sdr)],
            fill=(255, 255, 255, 255),
        )

    if five_overlay:
        overlay_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay_img)
        r_, g_, b_, _ = _rgba(PANEL)
        od.ellipse(
            [(cx - sri, cy - sri), (cx + sri, cy + sri)],
            fill=(r_, g_, b_, int(255 * OVERLAY_ALPHA)),
        )
        img = Image.alpha_composite(img, overlay_img)

    img = img.resize((total_w, h), Image.LANCZOS)
    return ImageTk.PhotoImage(img)


def render_bg(total_w, h, five_pct, seven_pct, five_overlay=False, compact=False, scale=1.0):
    """渲染主窗口背景：圆角面板 + 左右双环；
    compact=True 时走 _render_compact_bg（无超采样、二值边缘，避免杂色）；
    scale 等比缩放所有几何；five_overlay=True 时在左环内圆叠加遮罩。"""
    if compact:
        return _render_compact_bg(total_w, h, five_pct, five_overlay, scale)

    S    = SCALE
    img  = Image.new("RGBA", (total_w * S, h * S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    border = max(2, int(round(4 * scale)))
    radius = max(2, int(round(8 * scale)))
    draw.rounded_rectangle(
        [(border * S, border * S),
         ((total_w - border) * S, (h - border) * S)],
        radius=radius * S,
        fill=_rgba(PANEL),
    )
    cx_left = CX1 * scale
    cy_pos  = CY  * scale

    sro     = RO  * scale
    sri     = RI  * scale
    stw     = TRACK_W * scale
    smr     = (sro + sri) / 2
    sdr     = stw / 2

    ring_list = [(cx_left, five_pct), (total_w - cx_left, seven_pct)]
    for cx_o, pct in ring_list:
        cx, cy = cx_o * S, cy_pos * S
        ro = sro * S
        mr = smr * S
        tw = stw * S
        dr = sdr * S

        draw.arc(
            [(cx - ro, cy - ro), (cx + ro, cy + ro)],
            start=0, end=359.9, fill=_rgba(TRACK), width=max(1, int(tw)),
        )
        if pct and pct > 0.005:
            col   = ring_color(pct)
            sweep = min(pct, 1.0) * 360
            draw.arc(
                [(cx - ro, cy - ro), (cx + ro, cy + ro)],
                start=-90, end=-90 + sweep, fill=_rgba(col), width=max(1, int(tw)),
            )
            ang   = math.radians(-90 + sweep)
            dot_x = cx + mr * math.cos(ang)
            dot_y = cy + mr * math.sin(ang)
            draw.ellipse(
                [(dot_x - dr, dot_y - dr), (dot_x + dr, dot_y + dr)],
                fill=(255, 255, 255, 255),
            )

    if five_overlay:
        overlay_img = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay_img)
        cx, cy = cx_left * S, cy_pos * S
        ri = sri * S
        r_, g_, b_, _ = _rgba(PANEL)
        od.ellipse(
            [(cx - ri, cy - ri), (cx + ri, cy + ri)],
            fill=(r_, g_, b_, int(255 * OVERLAY_ALPHA)),
        )
        img = Image.alpha_composite(img, overlay_img)

    img = img.resize((total_w, h), Image.LANCZOS)
    return ImageTk.PhotoImage(img)


def load_png_icon(filename, size, tint=None, alpha=None):
    """从 icon/ 加载 PNG 并缩放，可选重染色 / 整体透明度。
    tint: 把所有非透明像素重染为该颜色（保留 alpha），适合单色图标的 hover 变色。
    alpha: 把所有非透明像素的 alpha 缩放该比例（整体透明度）。"""
    fp = ICON_DIR / filename
    if not fp.exists():
        return None
    try:
        img = Image.open(fp).convert("RGBA")
        img = img.resize((size, size), Image.LANCZOS)
        if tint or (alpha is not None and alpha < 1.0):
            px = img.load()
            if tint:
                r, g, b, _ = _rgba(tint)
            for y in range(img.height):
                for x in range(img.width):
                    pr, pg, pb, pa = px[x, y]
                    if pa > 0:
                        new_a = int(pa * alpha) if alpha is not None else pa
                        if tint:
                            px[x, y] = (r, g, b, new_a)
                        else:
                            px[x, y] = (pr, pg, pb, new_a)
        return ImageTk.PhotoImage(img)
    except Exception:
        return None


def load_gif_frames(path, max_w, max_h):
    """按 bbox (max_w, max_h) 等比缩放加载 GIF 所有帧。

    返回 (frames, out_w, out_h)；frames = [(PhotoImage, duration_ms), ...]。
    path 不存在或解码失败时返回 ([], 0, 0)。
    """
    frames = []
    if not path or not path.exists():
        return frames, 0, 0
    try:
        im = Image.open(path)
        ow, oh = im.size
        if ow <= 0 or oh <= 0:
            return frames, 0, 0
        # 等比缩放到 bbox 内
        scale = min(max_w / ow, max_h / oh, 1.0)
        # 若图本身比 bbox 小，也允许放大到 bbox（看起来更醒目）
        if ow < max_w and oh < max_h:
            scale = min(max_w / ow, max_h / oh)
        out_w = max(1, int(round(ow * scale)))
        out_h = max(1, int(round(oh * scale)))
        for i in range(getattr(im, "n_frames", 1)):
            im.seek(i)
            frame = im.convert("RGBA").resize((out_w, out_h), Image.LANCZOS)
            dur = im.info.get("duration", ANIM_FRAME_MS) or ANIM_FRAME_MS
            frames.append((ImageTk.PhotoImage(frame), int(dur)))
    except Exception:
        return frames, 0, 0
    return frames, out_w, out_h


def list_mascot_files():
    """mascot/ 下所有 .gif 文件名（仅 basename，按字母序）。"""
    if not MASCOT_DIR.exists():
        return []
    return sorted(p.name for p in MASCOT_DIR.glob("*.gif"))


def list_sound_files():
    """sounds/ 下所有 .mp3/.wav 文件名（仅 basename，按字母序）。"""
    if not SOUND_DIR.exists():
        return []
    files = list(SOUND_DIR.glob("*.mp3")) + list(SOUND_DIR.glob("*.wav"))
    return sorted({p.name for p in files})


def find_mascot_gif(preferred=None):
    """查找桌宠 GIF：
    1) preferred（cfg 里保存的文件名）
    2) asset/gif/<MASCOT_PRIMARY_NAME>（V3 默认）
    3) asset/gif/ 下任意 .gif（按文件名排序）
    都不存在返回 None。"""
    if preferred:
        p = MASCOT_DIR / preferred
        if p.exists():
            return p
    primary = MASCOT_DIR / MASCOT_PRIMARY_NAME
    if primary.exists():
        return primary
    gifs = list_mascot_files()
    if gifs:
        return MASCOT_DIR / gifs[0]
    return None


# MCI 句柄计数器，给每次播放一个独立 alias，避免并发覆盖
_MCI_COUNTER = [0]
# SETTINGS 试听用的固定 alias，切歌时先 close 旧的避免叠加
_MCI_PREVIEW_ALIAS = "cuwprev"


def play_preview_sound(path):
    """SETTINGS 下拉 hover 试听：先 close 上一段试听，再异步播放新的（不阻塞）。"""
    p = Path(path)
    if not p.exists():
        return
    sp = _short_path(p.resolve())

    def _go():
        """子线程实际执行：close 旧试听 → open 新文件 → play（不带 wait）。"""
        mci = ctypes.windll.winmm.mciSendStringW
        try: mci(f'close {_MCI_PREVIEW_ALIAS}', None, 0, None)
        except Exception: pass
        try:
            ret = mci(f'open "{sp}" type mpegvideo alias {_MCI_PREVIEW_ALIAS}',
                      None, 0, None)
            if ret != 0:
                ret = mci(f'open "{sp}" alias {_MCI_PREVIEW_ALIAS}',
                          None, 0, None)
            if ret == 0:
                # 不带 wait → 立刻返回；切歌时上面 close 会停掉
                mci(f'play {_MCI_PREVIEW_ALIAS}', None, 0, None)
        except Exception:
            pass
    threading.Thread(target=_go, daemon=True).start()


def stop_preview_sound():
    """关掉 SETTINGS 的试听 MCI 句柄。"""
    def _go():
        """子线程异步执行 MCI close（避免阻塞 UI）。"""
        try:
            ctypes.windll.winmm.mciSendStringW(
                f'close {_MCI_PREVIEW_ALIAS}', None, 0, None
            )
        except Exception:
            pass
    threading.Thread(target=_go, daemon=True).start()


def _short_path(p):
    """中文/空格路径用 8.3 短路径喂给 MCI，最稳。失败回退原路径字符串。"""
    try:
        buf = ctypes.create_unicode_buffer(260)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(p), buf, 260)
        if n and buf.value:
            return buf.value
    except Exception:
        pass
    return str(p)


def play_sound_async(path):
    """用 Windows MCI 播放 mp3/wav，不阻塞 UI。失败回退到 MessageBeep。"""
    p = Path(path)
    if not p.exists():
        try: ctypes.windll.user32.MessageBeep(0xFFFFFFFF)
        except Exception: pass
        return

    def _play():
        """子线程异步执行：分配独立 alias → open → play wait → close。"""
        _MCI_COUNTER[0] += 1
        alias = f"cuwsnd{_MCI_COUNTER[0]}"
        sp    = _short_path(p.resolve())
        mci   = ctypes.windll.winmm.mciSendStringW
        ok    = False
        try:
            ret = mci(f'open "{sp}" type mpegvideo alias {alias}', None, 0, None)
            if ret != 0:
                # 第二次尝试：不显式指定 type
                ret = mci(f'open "{sp}" alias {alias}', None, 0, None)
            if ret == 0:
                mci(f'play {alias} wait', None, 0, None)
                ok = True
        except Exception:
            ok = False
        finally:
            try: mci(f'close {alias}', None, 0, None)
            except: pass
        if not ok:
            try: ctypes.windll.user32.MessageBeep(0xFFFFFFFF)
            except: pass
    threading.Thread(target=_play, daemon=True).start()


def make_claude_icon(size=15):
    """生成左上角 Claude 图标：优先 icon/claude_crab.png → claude.png → 程序回退绘制。"""
    icon = load_png_icon("claude_crab.png", size)
    if icon is not None:
        return icon
    icon = load_png_icon("claude.png", size)
    if icon is not None:
        return icon
    S   = 4
    sz  = size * S
    img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    d   = ImageDraw.Draw(img)
    d.ellipse([(0, 0), (sz - 1, sz - 1)], fill=(210, 105, 55, 255))
    p  = sz // 4
    lw = max(2, sz // 5)
    d.arc([(p, p), (sz - p, sz - p)], start=50, end=310,
          fill=(255, 255, 255, 210), width=lw)
    img = img.resize((size, size), Image.LANCZOS)
    return ImageTk.PhotoImage(img)


# ── Widget ───────────────────────────────────────────────
class Widget:
    """悬浮组件主类：管理主窗口、双环渲染、ACCOUNT/SETTINGS 两个覆盖面板。"""

    def __init__(self):
        """初始化主窗口：加载配置、建画布、加载图标、绑定事件、首次刷新。"""
        self.cfg     = load_cfg()
        # 旧版本曾用 mascot_x/y 存绝对坐标 → 转成相对主窗口的偏移
        if ("mascot_off_x" not in self.cfg
                and "mascot_x" in self.cfg and "mascot_y" in self.cfg):
            base_mx = int(self.cfg.get("x", 0))
            base_my = int(self.cfg.get("y", 0))
            if base_mx or base_my:
                self.cfg["mascot_off_x"] = int(self.cfg["mascot_x"]) - base_mx
                self.cfg["mascot_off_y"] = int(self.cfg["mascot_y"]) - base_my
            self.cfg.pop("mascot_x", None)
            self.cfg.pop("mascot_y", None)
            save_cfg(self.cfg)
        self.data    = {}
        self.loading = False
        self._photo  = None
        self._dx = self._dy = None

        self._settings_open   = False
        self._animating       = False
        self._claude_icon     = None
        self._left_ring_hover = False
        self._refresh_big     = None
        # 当前活跃面板类型："account" 或 "settings"
        self._active_kind     = None

        # 面板三 Toplevel —— 全屏右键捕捉层 + 背景层（80%）+ 控件层（100%）
        self._settings_click_top = None
        self._settings_bg_panel = None
        self._settings_panel    = None
        self._bg_panel_canvas   = None
        self._panel_canvas      = None
        self._panel_bg_photo    = None
        self._panel_widgets     = []
        self._panel_cx          = W // 2
        self._panel_cy          = H // 2

        # 5-hour 用尽倒计时刷新 after id
        self._overlay_after_id = None
        # 周期刷新定时器 after id（修改频率时需要先取消）
        self._refresh_after_id = None

        # 紧凑模式状态：是否已贴右边收缩 + 收缩前的窗口位置
        self._compact          = False
        self._pre_compact_pos  = None

        # 右上角桌宠（独立 Toplevel，悬浮在主窗口外部右上角）
        self._mascot_top        = None
        self._mascot_label      = None
        self._gif_frames        = []
        self._gif_w             = 0
        self._gif_h             = 0
        self._gif_idx           = 0
        self._gif_after_id      = None
        # 桌宠拖动状态
        self._m_dx              = None
        self._m_dy              = None
        # 进入紧凑前的桌宠 y（紧凑模式下 x 固定贴右屏边、y 用此值保持）
        self._pre_compact_mascot_y = None

        # SETTINGS 面板的桌宠预览悬浮窗
        self._preview_top         = None
        self._preview_label       = None
        self._preview_frames      = []
        self._preview_idx         = 0
        self._preview_after_id    = None

        # Claude Code done flag 轮询
        self._done_after_id     = None
        self._done_last_mtime   = None

        # 上一次刷新拿到的 five_reset_at —— 用于检测"实际重置"：
        # 服务端给的 reset_at 是下次重置时刻，连续刷新值不变；一旦真重置过
        # 它会往后跳一大截（>60s）。此时播一次 reset_sound，不再依赖用量打满。
        self._last_five_reset_at = None

        # 主窗口
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)
        self.root.wm_attributes("-alpha", 0.95)
        self.root.wm_attributes("-transparentcolor", BG)
        self.root.configure(bg=BG)

        # 每次启动都居中于屏幕
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        init_x = max(0, (sw - W) // 2)
        init_y = max(0, (sh - H) // 2)
        self.root.geometry(f"{W}x{H}+{init_x}+{init_y}")

        self.cv = tk.Canvas(self.root, width=W, height=H,
                            bg=BG, highlightthickness=0)
        self.cv.pack()
        self.cv.bind("<ButtonPress-1>",   self._ds)
        self.cv.bind("<B1-Motion>",        self._dm)
        self.cv.bind("<ButtonRelease-1>",  self._de)
        self.cv.bind("<Double-Button-1>",  self._toggle_compact)
        self.cv.bind("<Motion>",           self._on_motion)
        self.cv.bind("<Leave>",            self._on_leave_canvas)

        self._claude_icon = make_claude_icon(15)

        self._btn_icons = {
            "btn_a": (load_png_icon("account.png", ICON_SZ, MUTED),
                      load_png_icon("account.png", ICON_SZ, YELLOW)),
            "btn_s": (load_png_icon("settings.png", ICON_SZ, MUTED),
                      load_png_icon("settings.png", ICON_SZ, GREEN)),
            "btn_q": (load_png_icon("close.png",    ICON_SZ, MUTED),
                      load_png_icon("close.png",    ICON_SZ, WHITE)),
        }

        self._refresh_big   = load_png_icon("refresh.png", 32, MUTED)
        self._refresh_small = load_png_icon("refresh.png",
                                            max(8, int(round(32 * COMPACT_SCALE))),
                                            MUTED)
        self._info_icon    = load_png_icon("info.png",    AC_INFO_SZ, MUTED)
        self._eye_icon     = load_png_icon("eye.png",     AC_EYE_SZ, MUTED)
        self._eye_off_icon = load_png_icon("eye-off.png", AC_EYE_SZ, MUTED)

        # 顶栏按钮：A=ACCOUNT 面板；S=SETTINGS 面板；✕=退出
        self.cv.tag_bind("btn_a", "<ButtonPress-1>",
                         lambda e: self._toggle_settings("account"))
        self.cv.tag_bind("btn_s", "<ButtonPress-1>",
                         lambda e: self._toggle_settings("settings"))
        self.cv.tag_bind("btn_q", "<ButtonPress-1>", lambda e: self._quit())
        for tag in ("btn_a", "btn_s", "btn_q"):
            self.cv.tag_bind(tag, "<Enter>",
                             lambda e, t=tag: self._set_btn_state(t, True))
            self.cv.tag_bind(tag, "<Leave>",
                             lambda e, t=tag: self._set_btn_state(t, False))

        # 加载桌宠 GIF + 创建独立悬浮窗
        self._load_and_show_mascot()

        self.draw()

        # 启动 GIF 循环 + done flag 轮询
        if self._gif_frames:
            self._tick_gif()
        # 首次同步要等主窗口真的就位
        self.root.after(50,  self._sync_mascot_pos)
        self.root.after(200, self._sync_mascot_pos)
        self._start_done_watch()

        if self.cfg.get("session_key"):
            self.root.after(300, self._refresh)
        else:
            self.root.after(600, lambda: self._toggle_settings("account"))

    def _set_btn_state(self, tag, hover):
        """切换右上角按钮的 hover 状态（切换 PNG 图层或文字 fill 颜色）。"""
        normal, hot = self._btn_icons.get(tag, (None, None))
        if normal is not None:
            img = hot if hover else normal
            self.cv.itemconfig(tag, image=img)
        else:
            self.cv.itemconfig(tag, fill=(WHITE if hover else MUTED))

    # ── 左环命中检测 ─────────────────────────────────────
    def _is_in_left_ring(self, x, y):
        """判断鼠标坐标 (x, y) 是否落在左环（5-Hour）的外圆内。紧凑模式下环居中于画布。"""
        if self._compact:
            cx_left = COMPACT_W / 2
            cy_pos  = COMPACT_H / 2
            ro      = RO * COMPACT_SCALE
        else:
            cx_left = CX1
            cy_pos  = CY
            ro      = RO
        dx, dy = x - cx_left, y - cy_pos
        return dx * dx + dy * dy <= ro * ro

    def _on_motion(self, e):
        """鼠标移动：检测是否进入/离开左环，切换光标并触发重绘（显示大刷新图标）。"""
        in_left = self._is_in_left_ring(e.x, e.y)
        if in_left != self._left_ring_hover:
            self._left_ring_hover = in_left
            self.cv.config(cursor=("hand2" if in_left else ""))
            self.draw()

    def _on_leave_canvas(self, e):
        """鼠标离开主画布：复位左环 hover 状态。"""
        if self._left_ring_hover:
            self._left_ring_hover = False
            self.cv.config(cursor="")
            self.draw()

    # ── 拖动 ─────────────────────────────────────────────
    def _ds(self, e):
        """鼠标按下：右上图标区不响应（紧凑模式无图标）；左环触发刷新；其他位置开始拖动。"""
        if self._animating:
            self._dx = self._dy = None
            return
        if not self._compact:
            in_icons = e.x > W - 62 and e.y < 28
            if in_icons:
                self._dx = self._dy = None
                return
        if self._is_in_left_ring(e.x, e.y):
            self._dx = self._dy = None
            self._refresh()
            return
        self._dx, self._dy = e.x, e.y

    def _dm(self, e):
        """鼠标拖动：移动主窗口，并让已开启的覆盖面板同步跟随。"""
        if self._dx is None:
            return
        nx = self.root.winfo_x() + e.x - self._dx
        ny = self.root.winfo_y() + e.y - self._dy
        self.root.geometry(f"+{nx}+{ny}")
        for top in (self._settings_bg_panel, self._settings_panel):
            if top is not None:
                try:
                    top.geometry(f"+{nx}+{ny}")
                except Exception:
                    pass
        self._sync_mascot_pos(nx, ny)
        self._sync_preview_pos()

    def _de(self, e):
        """鼠标松开：不再持久化位置（每次启动均居中）。"""
        if self._dx is None:
            return
        self._dx = self._dy = None

    def _toggle_compact(self, e=None):
        """双击窗体：未紧凑 → 缩到屏幕右边只显示 5-hour 环；已紧凑 → 复原到上次位置。"""
        if self._animating or self._settings_open:
            return
        # 左环单击用于刷新，避免双击在环内造成误触发
        if e is not None and self._is_in_left_ring(e.x, e.y) and not self._compact:
            return
        if not self._compact:
            try: self.root.update_idletasks()
            except Exception: pass
            cur_mx = self.root.winfo_x()
            cur_my = self.root.winfo_y()
            self._pre_compact_pos = (cur_mx, cur_my)
            # 用偏移确定算出桌宠当前 y（避免 winfo_y 偶发拿不到正确值）
            off_x, off_y = self._mascot_offset()
            self._pre_compact_mascot_y = cur_my + off_y
            sw = self.root.winfo_screenwidth()
            target_mx = max(0, sw - COMPACT_W)
            target_my = cur_my
            self.root.geometry(f"{COMPACT_W}x{COMPACT_H}+{target_mx}+{target_my}")
            self.cv.config(width=COMPACT_W, height=COMPACT_H)
            self._compact = True
        else:
            if self._pre_compact_pos is not None:
                target_mx, target_my = self._pre_compact_pos
            else:
                sw = self.root.winfo_screenwidth()
                sh = self.root.winfo_screenheight()
                target_mx = max(0, (sw - W) // 2)
                target_my = max(0, (sh - H) // 2)
            self.root.geometry(f"{W}x{H}+{target_mx}+{target_my}")
            self.cv.config(width=W, height=H)
            self._compact = False
            self._pre_compact_pos = None
            # 清掉快照 → 走正常偏移分支，桌宠按 offset 回到主窗左上角 + 偏移
            self._pre_compact_mascot_y = None
        self.draw()
        # 关键：直接用刚算出的 target 主窗坐标定位桌宠，不再依赖 winfo_x —
        # 否则在 geometry 还没落地的瞬间读到旧坐标会偶发"位置不变"。
        # 再排一个 after 兜底，处理极端 race 情况。
        self._sync_mascot_pos(target_mx, target_my)
        self.root.after(30, lambda: self._sync_mascot_pos(target_mx, target_my))
        self._update_mascot_cursor()

    # ── 右上角桌宠悬浮窗 ────────────────────────────────
    def _load_and_show_mascot(self):
        """根据 cfg["mascot_file"] / mascot_scale / mascot_show 加载并创建桌宠悬浮窗。"""
        if not bool(self.cfg.get("mascot_show", True)):
            self._gif_frames = []
            self._gif_w = self._gif_h = 0
            return
        gif_path = find_mascot_gif(self.cfg.get("mascot_file"))
        scale = float(self.cfg.get("mascot_scale", 1.0) or 1.0)
        scale = max(MASCOT_SCALE_MIN, min(MASCOT_SCALE_MAX, scale))
        bw = int(round(MASCOT_BBOX_W * scale))
        bh = int(round(MASCOT_BBOX_H * scale))
        self._gif_frames, self._gif_w, self._gif_h = load_gif_frames(
            gif_path, bw, bh
        )
        self._gif_idx = 0
        if self._gif_frames:
            self._create_mascot_window()

    def _apply_mascot_visibility(self):
        """根据 cfg['mascot_show'] 显示或隐藏桌宠悬浮窗（用于 SETTINGS 保存后立即生效）。"""
        if bool(self.cfg.get("mascot_show", True)):
            if self._mascot_top is None:
                self._reload_mascot()
        else:
            if self._gif_after_id is not None:
                try: self.root.after_cancel(self._gif_after_id)
                except: pass
                self._gif_after_id = None
            if self._mascot_top is not None:
                try: self._mascot_top.destroy()
                except: pass
            self._mascot_top   = None
            self._mascot_label = None
            self._gif_frames   = []

    def _reload_mascot(self):
        """SETTINGS 改了 mascot_file 后热重载：取消 tick → 销毁旧窗口 → 重建。"""
        if self._gif_after_id is not None:
            try: self.root.after_cancel(self._gif_after_id)
            except: pass
            self._gif_after_id = None
        if self._mascot_top is not None:
            try: self._mascot_top.destroy()
            except: pass
            self._mascot_top   = None
            self._mascot_label = None
        self._load_and_show_mascot()
        if self._gif_frames:
            self._tick_gif()
        self._sync_mascot_pos()

    # ── SETTINGS 面板：桌宠 GIF 预览悬浮窗（H×H 正方形，贴主窗右边） ─
    def _build_preview_window(self):
        """建一个 H×H 的透明正方形预览悬浮窗，贴在主窗右边。背景透明（用 BG keycolor）。"""
        if self._preview_top is not None:
            return
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.wm_attributes("-topmost", True)
        try: top.wm_attributes("-transparentcolor", BG)
        except Exception: pass
        top.configure(bg=BG)
        # Label 也用 BG 作背景 → 透明区域贯穿到桌面
        lbl = tk.Label(top, bg=BG, bd=0, highlightthickness=0)
        lbl.pack(fill="both", expand=True)
        self._preview_top   = top
        self._preview_label = lbl
        self._sync_preview_pos()

    def _sync_preview_pos(self):
        """预览窗：尺寸 H×H，紧贴主窗右边（main_x + W, main_y）。"""
        if self._preview_top is None:
            return
        try:
            self.root.update_idletasks()
            mx = self.root.winfo_x()
            my = self.root.winfo_y()
        except Exception:
            return
        try:
            self._preview_top.geometry(f"{H}x{H}+{mx + W}+{my}")
            self._preview_top.lift()
        except Exception:
            pass

    def _load_preview_gif(self, name):
        """按选择的 gif 文件名加载帧并启动预览循环。"""
        if self._preview_after_id is not None:
            try: self.root.after_cancel(self._preview_after_id)
            except: pass
            self._preview_after_id = None
        self._preview_frames = []
        self._preview_idx    = 0
        if not name or name == "(无)":
            if self._preview_label is not None:
                try: self._preview_label.config(image="", text="",
                                                bg=BG)
                except Exception: pass
            return
        p = MASCOT_DIR / name
        frames, _w, _h = load_gif_frames(p, H, H)
        if not frames or self._preview_label is None:
            return
        self._preview_frames = frames
        photo, dur = frames[0]
        try:
            self._preview_label.config(image=photo, text="")
            self._preview_label.image = photo
        except Exception:
            return
        self._preview_after_id = self.root.after(max(40, dur),
                                                 self._tick_preview)

    def _tick_preview(self):
        """预览 GIF 下一帧。"""
        self._preview_after_id = None
        if not self._preview_frames or self._preview_label is None:
            return
        self._preview_idx = (self._preview_idx + 1) % len(self._preview_frames)
        photo, dur = self._preview_frames[self._preview_idx]
        try:
            self._preview_label.config(image=photo)
            self._preview_label.image = photo
        except Exception:
            return
        self._preview_after_id = self.root.after(max(40, dur),
                                                 self._tick_preview)

    def _destroy_preview(self):
        """SETTINGS 关闭时销毁预览悬浮窗。"""
        if self._preview_after_id is not None:
            try: self.root.after_cancel(self._preview_after_id)
            except: pass
            self._preview_after_id = None
        if self._preview_top is not None:
            try: self._preview_top.destroy()
            except: pass
        self._preview_top   = None
        self._preview_label = None
        self._preview_frames = []
        self._preview_idx   = 0

    def _create_mascot_window(self):
        """在主窗口外部创建桌宠 Toplevel（无边框、透明背景、置顶、不抢焦点）。"""
        if self._mascot_top is not None or not self._gif_frames:
            return
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.wm_attributes("-topmost", True)
        try: top.wm_attributes("-transparentcolor", BG)
        except Exception: pass
        top.configure(bg=BG)
        top.geometry(f"{self._gif_w}x{self._gif_h}+0+0")
        lbl = tk.Label(top, bg=BG, bd=0, highlightthickness=0)
        lbl.pack(fill="both", expand=True)
        # 拖动桌宠：按下 / 拖动 / 松开 → 保存偏移到 cfg
        lbl.bind("<ButtonPress-1>",   self._mascot_ds)
        lbl.bind("<B1-Motion>",       self._mascot_dm)
        lbl.bind("<ButtonRelease-1>", self._mascot_de)
        # 右键 → 弹出缩放滑块（紧凑模式禁用）
        lbl.bind("<Button-3>",        self._mascot_show_resize_popup)
        # 点击不抢焦点
        try: top.attributes("-toolwindow", True)
        except Exception: pass
        self._mascot_top   = top
        self._mascot_label = lbl
        # 初始帧
        photo0, _ = self._gif_frames[0]
        lbl.config(image=photo0)
        lbl.image = photo0
        self._update_mascot_cursor()

    def _update_mascot_cursor(self):
        """紧凑模式下桌宠不可拖 → 光标变默认；正常模式 → 显示拖动手势。"""
        if self._mascot_label is None:
            return
        try:
            self._mascot_label.config(cursor=("" if self._compact else "fleur"))
        except Exception:
            pass

    def _mascot_offset(self):
        """返回 (off_x, off_y)：桌宠相对主窗左上角的偏移。
        cfg 没有保存值时给一个默认值——贴主窗外部右上角并下移 MASCOT_Y_OFFSET。"""
        ox = self.cfg.get("mascot_off_x")
        oy = self.cfg.get("mascot_off_y")
        if ox is not None and oy is not None:
            return int(ox), int(oy)
        mw = COMPACT_W if self._compact else W
        return (mw - self._gif_w), (-self._gif_h + MASCOT_Y_OFFSET)

    def _sync_mascot_pos(self, override_mx=None, override_my=None):
        """定位桌宠窗口：
        - 正常模式：position = 主窗左上角 + 偏移（偏移来自 cfg 或默认贴右上角）
        - 紧凑模式：x = 屏幕宽 - 桌宠宽（贴屏右边）；y = 进入紧凑前快照的 y
        如果传入 override_mx/my 就用它，避免读 winfo_x 时遇到 geometry 还没落地的 race。"""
        if self._mascot_top is None:
            return
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        except Exception:
            return

        if self._compact:
            gx = sw - self._gif_w
            gy = self._pre_compact_mascot_y
            if gy is None:
                gy = (override_my if override_my is not None else 0) + MASCOT_Y_OFFSET
        else:
            if override_mx is not None and override_my is not None:
                mx, my = override_mx, override_my
            else:
                try:
                    self.root.update_idletasks()
                    mx = self.root.winfo_x()
                    my = self.root.winfo_y()
                except Exception:
                    return
            off_x, off_y = self._mascot_offset()
            gx = mx + off_x
            gy = my + off_y

        gx = max(0, min(gx, sw - self._gif_w))
        gy = max(0, min(gy, sh - self._gif_h))
        try:
            self._mascot_top.geometry(
                f"{self._gif_w}x{self._gif_h}+{gx}+{gy}"
            )
            self._mascot_top.lift()
        except Exception:
            pass

    # ── 桌宠拖动（紧凑模式禁用） ─────────────────────────
    def _mascot_ds(self, e):
        """桌宠按下：紧凑模式不响应；正常模式进入拖动模式。"""
        if self._compact:
            self._m_dx = self._m_dy = None
            return
        self._m_dx, self._m_dy = e.x, e.y

    def _mascot_dm(self, e):
        """桌宠拖动：平移窗口。"""
        if self._m_dx is None or self._mascot_top is None or self._compact:
            return
        nx = self._mascot_top.winfo_pointerx() - self._m_dx
        ny = self._mascot_top.winfo_pointery() - self._m_dy
        try:
            self._mascot_top.geometry(f"+{nx}+{ny}")
        except Exception:
            pass

    def _mascot_de(self, e):
        """松手：写桌宠偏移到 cfg。"""
        if self._m_dx is None or self._mascot_top is None or self._compact:
            self._m_dx = self._m_dy = None
            return
        try:
            self.root.update_idletasks()
            mx = self.root.winfo_x()
            my = self.root.winfo_y()
            gx = self._mascot_top.winfo_x()
            gy = self._mascot_top.winfo_y()
            self.cfg["mascot_off_x"] = int(gx - mx)
            self.cfg["mascot_off_y"] = int(gy - my)
            # 清掉旧版本的绝对坐标键，避免误用
            self.cfg.pop("mascot_x", None)
            self.cfg.pop("mascot_y", None)
            save_cfg(self.cfg)
        except Exception:
            pass
        self._m_dx = self._m_dy = None

    def _mascot_show_resize_popup(self, _e=None):
        """右键桌宠：弹出 20%–200%（步进 10%）的缩放滑块。紧凑模式禁用。"""
        if self._compact or self._mascot_top is None:
            return
        # 已打开的弹窗 / 覆盖层先关掉
        old = getattr(self, "_resize_popup", None)
        if old is not None:
            try: old.destroy()
            except Exception: pass
            self._resize_popup = None
        old_ov = getattr(self, "_resize_overlay", None)
        if old_ov is not None:
            try: old_ov.destroy()
            except Exception: pass
            self._resize_overlay = None

        cur_scale = float(self.cfg.get("mascot_scale", 1.0) or 1.0)
        cur_pct   = int(round(max(0.2, min(2.0, cur_scale)) * 10)) * 10
        cur_pct   = max(20, min(200, cur_pct))

        # 紧凑单行布局：[滑块] [值]  —— 无背景框、右键关闭
        RP_PAD_X    = 4
        RP_PAD_Y    = 2
        RP_SLIDER_W = 140
        RP_ROW_H    = 18
        RP_VAL_W    = 32
        RP_GAP      = 6
        RP_KNOB_R   = 7
        RP_TRACK_H  = 5
        RP_PCT_MIN  = 20
        RP_PCT_MAX  = 200
        RP_PCT_STEP = 10

        inner_w = RP_SLIDER_W + RP_GAP + RP_VAL_W
        outer_w = inner_w + RP_PAD_X * 2
        outer_h = RP_ROW_H + RP_PAD_Y * 2

        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.wm_attributes("-topmost", True)
        try: top.wm_attributes("-transparentcolor", BG)
        except Exception: pass
        top.configure(bg=BG)

        # 透明背景 Canvas：BG 作 color-key 透明，仅滑块与文字可见
        cv = tk.Canvas(top, width=outer_w, height=outer_h,
                       bg=BG, highlightthickness=0, bd=0)
        cv.pack()

        pct_state = {"v": cur_pct, "photo": None}

        def _val_to_x(v, w):
            rng = RP_PCT_MAX - RP_PCT_MIN
            frac = (v - RP_PCT_MIN) / rng if rng else 0
            return RP_KNOB_R + frac * (w - 2 * RP_KNOB_R)

        def _x_to_val(x, w):
            usable = w - 2 * RP_KNOB_R
            if usable <= 0:
                return RP_PCT_MIN
            frac = max(0.0, min(1.0, (x - RP_KNOB_R) / usable))
            raw = RP_PCT_MIN + frac * (RP_PCT_MAX - RP_PCT_MIN)
            return int(round(raw / RP_PCT_STEP) * RP_PCT_STEP)

        def _redraw_slider():
            """PIL 超采样渲染圆角轨道 + 已选段 + 白色 knob，透明背景。"""
            S    = SCALE
            w, h = RP_SLIDER_W, RP_ROW_H
            img  = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
            d    = ImageDraw.Draw(img)
            cy   = (h * S) // 2
            th   = RP_TRACK_H * S
            kr   = RP_KNOB_R * S
            half = th // 2
            d.rounded_rectangle(
                [(kr, cy - half), (w * S - kr, cy + half)],
                radius=half, fill=_rgba(ENTRY),
            )
            knob_x = int(_val_to_x(pct_state["v"], w) * S)
            if knob_x > kr:
                d.rounded_rectangle(
                    [(kr, cy - half), (knob_x, cy + half)],
                    radius=half, fill=_rgba(YELLOW),
                )
            d.ellipse(
                [(knob_x - kr, cy - kr), (knob_x + kr, cy + kr)],
                fill=_rgba(WHITE), outline=_rgba(BORDER), width=max(1, S),
            )
            img = img.resize((w, h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            pct_state["photo"] = photo
            cv.delete("slider")
            cv.create_image(RP_PAD_X, RP_PAD_Y, anchor="nw",
                            image=photo, tags="slider")

        def _update_val_label():
            cv.itemconfigure("val", text=f"{pct_state['v']}%")

        # 全屏透明覆盖层（右键 / 左键空白处关闭弹窗）
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        except Exception:
            sw, sh = 1920, 1080
        ov = tk.Toplevel(self.root)
        ov.overrideredirect(True)
        ov.wm_attributes("-topmost", True)
        try: ov.wm_attributes("-alpha", 0.01)
        except Exception: pass
        ov.configure(bg="black")
        ov.geometry(f"{sw}x{sh}+0+0")

        def _on_close(_=None):
            try:
                self.cfg["mascot_scale"] = round(pct_state["v"] / 100.0, 3)
                save_cfg(self.cfg)
            except Exception:
                pass
            try: top.destroy()
            except Exception: pass
            try: ov.destroy()
            except Exception: pass
            self._resize_popup = None

        ov.bind("<Button-3>", _on_close)
        ov.bind("<Button-1>", _on_close)

        def _on_drag(e):
            # 鼠标 x 是 Canvas 内坐标，需要减去滑块左侧偏移
            v = _x_to_val(e.x - RP_PAD_X, RP_SLIDER_W)
            if v != pct_state["v"]:
                pct_state["v"] = v
                _redraw_slider()
                _update_val_label()
                # 缩放时桌宠右上角不动
                self._reload_mascot_frames(v / 100.0,
                                           keep_window=True,
                                           anchor="top_right")

        slider_x0 = RP_PAD_X
        slider_x1 = slider_x0 + RP_SLIDER_W
        val_x0    = slider_x1 + RP_GAP

        _redraw_slider()

        # 值文本
        cv.create_text(val_x0 + RP_VAL_W // 2,
                       RP_PAD_Y + RP_ROW_H // 2,
                       text=f"{cur_pct}%",
                       fill=YELLOW, font=("Segoe UI", 9, "bold"),
                       anchor="center", tags="val")

        def _hit_slider(x, y):
            return (slider_x0 <= x <= slider_x1
                    and RP_PAD_Y <= y <= RP_PAD_Y + RP_ROW_H)

        def _on_cv_press(e):
            if _hit_slider(e.x, e.y):
                cv.config(cursor="hand2")
                _on_drag(e)

        def _on_cv_motion_btn(e):
            if _hit_slider(e.x, e.y) or cv.cget("cursor") == "hand2":
                _on_drag(e)

        def _on_cv_release(_e):
            cv.config(cursor="")

        def _on_cv_hover(e):
            if _hit_slider(e.x, e.y):
                cv.config(cursor="hand2")
            else:
                cv.config(cursor="")

        cv.bind("<Button-1>",        _on_cv_press)
        cv.bind("<B1-Motion>",       _on_cv_motion_btn)
        cv.bind("<ButtonRelease-1>", _on_cv_release)
        cv.bind("<Motion>",          _on_cv_hover)
        # 右键关闭
        cv.bind("<Button-3>",        _on_close)
        top.bind("<Button-3>",       _on_close)
        top.bind("<Escape>",         _on_close)
        top.update_idletasks()
        try: top.focus_set()
        except Exception: pass

        # 定位：贴在桌宠顶部（popup 底边对齐桌宠顶边），不够位置则放下方
        try:
            mx = self._mascot_top.winfo_x()
            my = self._mascot_top.winfo_y()
            px = mx + (self._gif_w - outer_w) // 2
            py = my - outer_h - 4
            if py < 0:
                py = my + self._gif_h + 4
            px = max(0, min(px, sw - outer_w))
            py = max(0, py)
            top.geometry(f"{outer_w}x{outer_h}+{px}+{py}")
            top.lift()  # 保证浮在 overlay 之上
        except Exception:
            pass

        self._resize_popup = top
        self._resize_overlay = ov

    def _reload_mascot_frames(self, scale, keep_window=False, anchor="top_left"):
        """按新 scale 重新加载 GIF 帧并应用到当前桌宠窗口（不销毁窗口、不重启 tick）。
        keep_window=True：保留当前窗口位置，仅调整尺寸。
        anchor='top_left'  → 左上角不动（默认）；
        anchor='top_right' → 右上角不动（向左 / 向下扩展）。"""
        scale = max(MASCOT_SCALE_MIN, min(MASCOT_SCALE_MAX, float(scale)))
        bw = int(round(MASCOT_BBOX_W * scale))
        bh = int(round(MASCOT_BBOX_H * scale))
        gif_path = find_mascot_gif(self.cfg.get("mascot_file"))
        frames, w, h = load_gif_frames(gif_path, bw, bh)
        if not frames:
            return
        old_w = self._gif_w
        self._gif_frames = frames
        self._gif_w, self._gif_h = w, h
        if self._gif_idx >= len(frames):
            self._gif_idx = 0
        if self._mascot_top is not None:
            try:
                if keep_window:
                    gx = self._mascot_top.winfo_x()
                    gy = self._mascot_top.winfo_y()
                    if anchor == "top_right":
                        # 右上角锚定：旧右边 = gx + old_w；新 x = 旧右边 - new_w
                        gx = gx + (old_w - w)
                    self._mascot_top.geometry(f"{w}x{h}+{gx}+{gy}")
                else:
                    self._mascot_top.geometry(f"{w}x{h}+0+0")
            except Exception:
                pass
        if self._mascot_label is not None:
            photo, _ = frames[self._gif_idx]
            try:
                self._mascot_label.config(image=photo)
                self._mascot_label.image = photo
            except Exception:
                pass

    def _tick_gif(self):
        """切换 GIF 下一帧并按帧自带的 duration 安排下一次。"""
        self._gif_after_id = None
        if not self._gif_frames or self._mascot_label is None:
            return
        self._gif_idx = (self._gif_idx + 1) % len(self._gif_frames)
        photo, dur = self._gif_frames[self._gif_idx]
        try:
            self._mascot_label.config(image=photo)
            self._mascot_label.image = photo
        except Exception:
            pass
        self._gif_after_id = self.root.after(max(40, dur), self._tick_gif)

    # ── Claude Code done flag 监听 ───────────────────────
    def _start_done_watch(self):
        """启动 done flag 文件轮询；mtime 变化即触发提示音并删除 flag。"""
        try:
            DONE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        if DONE_FLAG.exists():
            try: self._done_last_mtime = DONE_FLAG.stat().st_mtime
            except Exception: self._done_last_mtime = None
        self._done_after_id = self.root.after(DONE_POLL_MS, self._poll_done)

    def _poll_done(self):
        """轮询 done flag：发现新文件就播 done 提示音，然后删掉。"""
        self._done_after_id = None
        try:
            if DONE_FLAG.exists():
                try:
                    mt = DONE_FLAG.stat().st_mtime
                except Exception:
                    mt = None
                if mt is not None and mt != self._done_last_mtime:
                    self._done_last_mtime = mt
                    play_sound_async(SOUND_DIR / self.cfg.get("done_sound", DONE_SOUND_DEFAULT))
                    try: DONE_FLAG.unlink()
                    except Exception: pass
                    self._done_last_mtime = None
        except Exception:
            pass
        self._done_after_id = self.root.after(DONE_POLL_MS, self._poll_done)

    # ── 操作 ─────────────────────────────────────────────
    def _quit(self):
        """关闭按钮：取消挂起的定时器、销毁桌宠窗口后退出 mainloop。"""
        for aid_attr in ("_overlay_after_id", "_refresh_after_id",
                         "_gif_after_id", "_done_after_id",
                         "_preview_after_id"):
            aid = getattr(self, aid_attr, None)
            if aid is not None:
                try: self.root.after_cancel(aid)
                except: pass
                setattr(self, aid_attr, None)
        if self._mascot_top is not None:
            try: self.root.update_idletasks(); self._mascot_top.destroy()
            except Exception: pass
            self._mascot_top = None
            self._mascot_label = None
        self._destroy_preview()
        self.root.quit()

    def _refresh(self):
        """手动/定时刷新用量：起子线程拉 API，并按 cfg 的频率安排下一次刷新。"""
        if self.loading:
            return
        self.loading = True
        self.draw()
        threading.Thread(target=self._fetch, daemon=True).start()
        if self._refresh_after_id is not None:
            try: self.root.after_cancel(self._refresh_after_id)
            except: pass
        interval = int(self.cfg.get("refresh_min", REFRESH_MIN_DEFAULT))
        interval = max(REFRESH_MIN_MIN, min(REFRESH_MIN_MAX, interval))
        self._refresh_after_id = self.root.after(interval * 60 * 1000, self._refresh)

    def _fetch(self):
        """子线程：调 fetch_usage + parse，结果回投到主线程的 _done。"""
        try:
            result = parse(fetch_usage(self.cfg["session_key"], self.cfg["org_id"]))
        except Exception as e:
            result = {"error": str(e)}
        self.root.after(0, self._done, result)

    def _done(self, r):
        """主线程收到子线程结果：清 loading、存数据、重绘。

        副作用：若 five_reset_at 比上一次往后跳了 >60 秒，认为发生过真实重置，
        播一次 reset_sound。这样即使用量未打满也能在重置时刻得到提示音。"""
        self.loading = False
        self.data    = r
        cur = r.get("five_reset_at") if isinstance(r, dict) else None
        prev = self._last_five_reset_at
        if cur is not None:
            if prev is not None:
                try:
                    if (cur - prev).total_seconds() > 60:
                        play_sound_async(
                            SOUND_DIR / self.cfg.get("reset_sound",
                                                     RESET_SOUND_DEFAULT)
                        )
                except Exception:
                    pass
            self._last_five_reset_at = cur
        self.draw()

    # ── 覆盖面板展开/收起（ACCOUNT 与 SETTINGS 共用动画） ────
    def _toggle_settings(self, kind="account"):
        """切换覆盖面板的展开/收起状态；kind 仅在展开时生效。"""
        if self._animating:
            return
        if self._settings_open:
            self._start_collapse()
        else:
            self._active_kind = kind
            self._start_expand()

    def _start_expand(self):
        """展开阶段 1：创建覆盖面板并播放空白圆角矩形由中心扩散动画。"""
        self._animating     = True
        self._settings_open = True
        self._create_settings_panel()
        self._do_bg_anim(0.0, 1.0, 0, on_done=self._after_bg_expand)

    def _after_bg_expand(self):
        """展开阶段 2：背景动画结束后按当前面板类型构建控件并播放控件展开动画。"""
        if self._active_kind == "settings":
            self._build_st_controls()
        else:
            self._build_panel_controls()
        self._set_panel_progress(0.0)
        self._do_panel_anim(0.0, 1.0, 0, on_done=self._anim_done)

    def _start_collapse(self):
        """收起：一气呵成的反向动画 —— widgets 由四角收回中心 → 背景由全屏收回中心 →
        销毁 Toplevel。一次点击触发完整动画，结束直接回到主窗口。"""
        self._animating     = True
        self._settings_open = False
        self._destroy_preview()
        stop_preview_sound()
        self._do_panel_anim(1.0, 0.0, 0, on_done=self._after_controls_collapse)

    def _after_controls_collapse(self):
        """收起阶段 2：销毁控件，再播放空白面板由四角收回中心的动画。"""
        self._destroy_panel_controls()
        self._do_bg_anim(1.0, 0.0, 0, on_done=self._after_bg_collapse)

    def _after_bg_collapse(self):
        """收起阶段 3：背景收完后销毁 Toplevel。"""
        self._destroy_panel()
        self._anim_done()

    def _anim_done(self):
        """动画整体结束的统一收尾：清 animating 标志 + 清面板类型。"""
        self._animating = False
        if not self._settings_open:
            self._active_kind = None

    # ── 面板创建/销毁 ─────────────────────────────────────
    def _create_settings_panel(self):
        """创建三 Toplevel：
        - 屏幕全屏透明覆盖层：捕捉屏幕任意位置右键 → 关闭面板
        - 背景层：半透明圆角面板
        - 控件层：放 label/entry/button/icon（alpha=1.0）
        关闭：右键屏幕任意处 / Esc。"""
        if self._settings_panel is not None:
            return

        x = self.root.winfo_x()
        y = self.root.winfo_y()
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        except Exception:
            sw, sh = 1920, 1080

        # 屏幕全屏透明覆盖层：右键 → 关闭面板（任意位置都触发）
        click_top = tk.Toplevel(self.root)
        click_top.overrideredirect(True)
        click_top.wm_attributes("-topmost", True)
        try: click_top.wm_attributes("-alpha", 0.01)
        except Exception: pass
        click_top.configure(bg="black")
        click_top.geometry(f"{sw}x{sh}+0+0")
        click_top.bind("<Button-3>", lambda e: self._toggle_settings())

        # 背景层：仅渲染圆角面板，alpha=0.80
        bg_top = tk.Toplevel(self.root)
        bg_top.overrideredirect(True)
        bg_top.wm_attributes("-topmost", True)
        try:
            bg_top.wm_attributes("-transparentcolor", BG)
        except Exception:
            pass
        try:
            bg_top.wm_attributes("-alpha", ACCOUNT_PANEL_ALPHA)
        except Exception:
            pass
        bg_top.configure(bg=BG)
        bg_top.geometry(f"{W}x{H}+{x}+{y}")
        bg_cv = tk.Canvas(bg_top, width=W, height=H,
                          bg=BG, highlightthickness=0)
        bg_cv.pack()
        # 面板内右键也关闭（兜底，比如鼠标已经在面板上）
        bg_cv.bind("<Button-3>", lambda e: self._toggle_settings())

        # 控件层：放 label/entry/button/icon，alpha=1.0
        overlay = tk.Toplevel(self.root)
        overlay.overrideredirect(True)
        overlay.wm_attributes("-topmost", True)
        try:
            overlay.wm_attributes("-transparentcolor", BG)
        except Exception:
            pass
        try:
            overlay.wm_attributes("-alpha", 1.0)
        except Exception:
            pass
        overlay.configure(bg=BG)
        overlay.geometry(f"{W}x{H}+{x}+{y}")

        panel_cv = tk.Canvas(overlay, width=W, height=H,
                             bg=BG, highlightthickness=0)
        panel_cv.pack()
        panel_cv.bind("<Button-3>", lambda e: self._toggle_settings())
        overlay.bind("<Escape>",   lambda e: self._toggle_settings())
        overlay.bind("<Button-3>", lambda e: self._toggle_settings())
        overlay.focus_force()
        # 控件层 / 背景层 lift 到全屏 click_top 之上
        try:
            bg_top.lift()
            overlay.lift()
        except Exception:
            pass

        self._settings_click_top = click_top
        self._settings_bg_panel  = bg_top
        self._bg_panel_canvas    = bg_cv
        self._settings_panel     = overlay
        self._panel_canvas       = panel_cv

    def _on_panel_click(self, e):
        """面板空白处点击：关闭面板（动画中忽略）。"""
        if self._animating:
            return
        self._toggle_settings()

    def _destroy_panel_controls(self):
        """销毁面板上的所有 tk 控件（收起阶段先于销毁 Toplevel 调用）。"""
        for widget, *_ in self._panel_widgets:
            try:
                widget.destroy()
            except Exception:
                pass
        self._panel_widgets = []

    def _destroy_panel(self):
        """销毁覆盖 Toplevel（含背景层、控件层、全屏右键捕捉层）并清空相关引用。"""
        if self._bg_panel_canvas is not None:
            try:
                self._bg_panel_canvas.delete("bg")
            except Exception:
                pass
        for top_attr in ("_settings_panel", "_settings_bg_panel",
                         "_settings_click_top"):
            top = getattr(self, top_attr, None)
            if top is not None:
                try:
                    top.destroy()
                except Exception:
                    pass
            setattr(self, top_attr, None)
        self._panel_canvas    = None
        self._bg_panel_canvas = None
        self._panel_bg_photo  = None
        self._panel_widgets   = []

    # ── 空白面板 PIL 圆角矩形渲染 + 由中心扩散动画 ─────────
    def _render_panel_bg(self, w, h):
        """渲染指定 w×h 的圆角面板背景（PIL 超采样后缩回）用于扩散动画当前帧。"""
        if w < 4 or h < 4:
            return None
        S = SCALE
        img = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        radius = max(2, min(8, w // 4, h // 4)) * S
        draw.rounded_rectangle(
            [(0, 0), (w * S - 1, h * S - 1)],
            radius=radius,
            fill=_rgba(PANEL),
        )
        img = img.resize((w, h), Image.LANCZOS)
        return ImageTk.PhotoImage(img)

    def _set_bg_progress(self, progress):
        """根据 0-1 进度把面板背景缩放并居中绘制（0=中心点、1=全尺寸 W×H）。"""
        if self._bg_panel_canvas is None:
            return
        cur_w = max(2, int(W * progress))
        cur_h = max(2, int(H * progress))
        cur_x = (W - cur_w) // 2
        cur_y = (H - cur_h) // 2
        photo = self._render_panel_bg(cur_w, cur_h)
        self._panel_bg_photo = photo
        try:
            self._bg_panel_canvas.delete("bg")
            if photo is not None:
                self._bg_panel_canvas.create_image(
                    cur_x, cur_y, anchor="nw",
                    image=photo, tags="bg",
                )
                self._bg_panel_canvas.tag_lower("bg")
        except Exception:
            pass

    def _do_bg_anim(self, from_p, to_p, step, on_done=None):
        """背景扩散/收回动画的递归驱动：用 ease-in-out cubic 插值到当前帧。"""
        steps = ACCOUNT_BG_ANIM_STEPS
        if steps <= 0:
            self._set_bg_progress(to_p)
            if on_done is not None:
                on_done()
            return
        t = step / steps
        if t < 0.5:
            t = 4 * t * t * t
        else:
            t = 1 - (-2 * t + 2) ** 3 / 2
        progress = from_p + (to_p - from_p) * t
        if step >= steps:
            progress = to_p
        self._set_bg_progress(progress)
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        if step < steps:
            self.root.after(ACCOUNT_ANIM_MS,
                            lambda: self._do_bg_anim(from_p, to_p, step + 1, on_done))
        else:
            if on_done is not None:
                on_done()

    # ── 面板控件由中心向四角展开/收拢 ─────────────────────
    def _set_panel_progress(self, progress):
        """根据 0-1 进度把每个控件从中心位置向最终位置插值（含尺寸缩放）。"""
        if not self._panel_widgets:
            return
        cx, cy = self._panel_cx, self._panel_cy
        for widget, fx, fy, fw, fh in self._panel_widgets:
            cur_w = max(1, int(fw * progress))
            cur_h = max(1, int(fh * progress))
            final_cx = fx + fw // 2
            final_cy = fy + fh // 2
            cur_cx = int(cx + (final_cx - cx) * progress)
            cur_cy = int(cy + (final_cy - cy) * progress)
            try:
                widget.place_configure(
                    x=cur_cx - cur_w // 2,
                    y=cur_cy - cur_h // 2,
                    width=cur_w, height=cur_h,
                )
            except Exception:
                pass

    def _do_panel_anim(self, from_p, to_p, step, on_done=None):
        """面板控件展开/收回动画的递归驱动（ease-in-out cubic）。"""
        pa_steps = ACCOUNT_PANEL_ANIM_STEPS
        if pa_steps <= 0:
            self._set_panel_progress(to_p)
            if on_done:
                on_done()
            return
        t = step / pa_steps
        if t < 0.5:
            t = 4 * t * t * t
        else:
            t = 1 - (-2 * t + 2) ** 3 / 2
        progress = from_p + (to_p - from_p) * t
        if step >= pa_steps:
            progress = to_p
        self._set_panel_progress(progress)
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        if step < pa_steps:
            self.root.after(ACCOUNT_ANIM_MS,
                            lambda: self._do_panel_anim(from_p, to_p, step + 1, on_done))
        else:
            if on_done is not None:
                on_done()

    def _bind_eye(self, eye_label, entry):
        """给输入框绑定眼睛图标：点击切换密文（•）/ 明文显示。"""
        eye_img     = self._eye_icon
        eye_off_img = self._eye_off_icon

        def _toggle(_=None):
            """点击眼睛：根据当前 show 字符切换显隐 + 切换 eye/eye-off 图标。"""
            if entry.cget("show"):
                entry.config(show="")
                if eye_img is not None:
                    eye_label.config(image=eye_img)
                    eye_label.image = eye_img
                else:
                    eye_label.config(text="明文")
            else:
                entry.config(show="•")
                if eye_off_img is not None:
                    eye_label.config(image=eye_off_img)
                    eye_label.image = eye_off_img
                else:
                    eye_label.config(text="密文")
        eye_label.bind("<Button-1>", _toggle)

    def _build_panel_controls(self):
        """构建 ACCOUNT 面板控件：sessionKey / Organization ID 两组输入和保存按钮。"""
        if self._panel_canvas is None:
            return

        parent = self._panel_canvas

        AC_TOP    = RO_GAP
        AC_BOTTOM = H

        try:
            f_bold  = tkfont.Font(family="Segoe UI", size=10, weight="bold")
            AC_label_w = f_bold.measure("Organization ID")
        except Exception:
            AC_label_w = 110
        AC_ENTRY_W = W - RO_GAP * 2
        AC_ENTRY_X = RO_GAP

        def _info_label(p, tip_text):
            """构造一个带 tooltip 的 ⓘ 信息图标 Label。"""
            if self._info_icon is not None:
                lbl = tk.Label(p, image=self._info_icon, bg=PANEL,
                               cursor="hand2")
                lbl.image = self._info_icon
            else:
                lbl = tk.Label(p, text="i", bg=PANEL, fg=MUTED,
                               font=("Segoe UI", 10), cursor="hand2")
            ToolTip(lbl, tip_text)
            return lbl

        def _eye_label(p):
            """构造一个初始为 eye-off（隐藏）状态的眼睛切换 Label。"""
            if self._eye_off_icon is not None:
                lbl = tk.Label(p, image=self._eye_off_icon, bg=PANEL,
                               cursor="hand2")
                lbl.image = self._eye_off_icon
            else:
                lbl = tk.Label(p, text="密文", bg=PANEL, fg=MUTED,
                               font=("Segoe UI Emoji", 10), cursor="hand2")
            return lbl

        AC_LABEL_H = 20
        AC_ENTRY_H = 22
        AC_BTN_H   = 22
        AC_GAP     = 4
        AC_sk_label_y  = AC_TOP
        AC_sk_entry_y  = AC_sk_label_y + AC_LABEL_H + AC_GAP
        AC_oid_label_y = AC_sk_entry_y + AC_ENTRY_H + AC_GAP
        AC_oid_entry_y = AC_oid_label_y + AC_LABEL_H + AC_GAP
        AC_btn_y = H

        sk_row = tk.Frame(parent, bg=PANEL)
        sk_row.place(x=AC_ENTRY_X, y=AC_sk_label_y, width=AC_ENTRY_W, height=AC_LABEL_H)
        sk_row_c = tk.Frame(sk_row, bg=PANEL)
        sk_row_c.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(sk_row_c, text="sessionKey", bg=PANEL, fg=WHITE,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        _info_label(
            sk_row_c,
            "登录 claude.ai → setting →  usage\n"
            "F12 → 网络 → F5刷新页面 \n"
            "→ 搜索 sessionKey → 找到标黄底色的Cookie\n"
            "→ 复制 sessionKey=sk-ant-... 的值\n"
            "→ 此值禁用从文本框中复制的权限，不展示明文",
        ).pack(side="left", padx=(ICON_GAP, ICON_GAP))
        # session_key 高敏感：不提供眼睛切换、不允许复制/剪切，避免明文外泄

        sk_v = tk.StringVar(value=self.cfg.get("session_key", ""))
        sk_entry = tk.Entry(
            parent, textvariable=sk_v, show="•",
            bg=ENTRY, fg=WHITE, insertbackground=WHITE,
            font=("Consolas", 8), relief="flat", bd=0,
            highlightthickness=1,
            highlightbackground=WHITE,
            highlightcolor=YELLOW,
            justify="left",
        )
        sk_entry.place(x=AC_ENTRY_X, y=AC_sk_entry_y, width=AC_ENTRY_W, height=AC_ENTRY_H)

        # 屏蔽 Ctrl+C / Ctrl+X / Ctrl+Insert / Shift+Delete / 右键菜单 / 中键粘贴回显
        # （Tk 的 show=• 只影响渲染，默认 Ctrl+C 仍会复制到剪贴板的是明文）
        def _block(_e):
            return "break"
        for seq in (
            "<Control-c>", "<Control-C>",
            "<Control-x>", "<Control-X>",
            "<Control-Insert>", "<Shift-Delete>",
            "<Button-3>",            # 右键菜单
            "<Button-2>",            # 中键（X11 风格的明文粘贴）
            "<<Copy>>", "<<Cut>>",   # Tk 虚拟事件兜底
        ):
            sk_entry.bind(seq, _block)

        oid_row = tk.Frame(parent, bg=PANEL)
        oid_row.place(x=AC_ENTRY_X, y=AC_oid_label_y, width=AC_ENTRY_W, height=AC_LABEL_H)
        oid_row_c = tk.Frame(oid_row, bg=PANEL)
        oid_row_c.place(relx=0.5, rely=0.5, anchor="center")
        tk.Label(oid_row_c, text="Organization ID", bg=PANEL, fg=WHITE,
                 font=("Segoe UI", 10, "bold")).pack(side="left")
        _info_label(
            oid_row_c,
            "登录 claude.ai\n"
            "→ 右上角头像 → Settings → Account\n"
            "→ 复制 Organization ID",
        ).pack(side="left", padx=(ICON_GAP, ICON_GAP))
        oid_eye = _eye_label(oid_row_c)
        oid_eye.pack(side="left")

        oid_v = tk.StringVar(value=self.cfg.get("org_id", ""))
        oid_entry = tk.Entry(
            parent, textvariable=oid_v, show="•",
            bg=ENTRY, fg=WHITE, insertbackground=WHITE,
            font=("Consolas", 8), relief="flat", bd=0,
            highlightthickness=1,
            highlightbackground=WHITE,
            highlightcolor=YELLOW,
            justify="left",
        )
        oid_entry.place(x=AC_ENTRY_X, y=AC_oid_entry_y, width=AC_ENTRY_W, height=AC_ENTRY_H)
        self._bind_eye(oid_eye, oid_entry)

        def _save():
            """保存按钮回调：把两个输入写入配置并触发一次刷新。"""
            sk  = sk_v.get().strip()
            oid = oid_v.get().strip()
            if not sk or not oid:
                return
            self.cfg.update(session_key=sk, org_id=oid)
            save_cfg(self.cfg)
            self._toggle_settings()
            self.root.after(380, self._refresh)

        save_btn = tk.Button(
            parent,
            text="保             存",
            command=_save,
            bg=GREEN,
            fg=WHITE,
            activebackground=YELLOW,
            activeforeground=WHITE,
            relief="flat",
            bd=0,
            padx=14, pady=2, font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        save_btn.place(x=AC_ENTRY_X, y=AC_btn_y, anchor="sw",
                       width=AC_ENTRY_W, height=AC_BTN_H)

        self._panel_widgets = [
            (sk_row,    AC_ENTRY_X, AC_sk_label_y,       AC_ENTRY_W, AC_LABEL_H),
            (sk_entry,  AC_ENTRY_X, AC_sk_entry_y,       AC_ENTRY_W, AC_ENTRY_H),
            (oid_row,   AC_ENTRY_X, AC_oid_label_y,      AC_ENTRY_W, AC_LABEL_H),
            (oid_entry, AC_ENTRY_X, AC_oid_entry_y,      AC_ENTRY_W, AC_ENTRY_H),
            (save_btn,  AC_ENTRY_X, AC_BOTTOM - AC_BTN_H, AC_ENTRY_W, AC_BTN_H),
        ]
        self._panel_cx = W // 2
        self._panel_cy = (AC_TOP + AC_BOTTOM) // 2

    def _build_st_controls(self):
        """构建 SETTINGS 面板控件：单行「刷新频率 [slider] [值] 分钟」+ 底部双按钮 +
        贴底警告（变量均以 ST_ 起）。滑槽两端为半圆，使用 PIL 超采样保证边缘清晰。"""
        if self._panel_canvas is None:
            return

        parent = self._panel_canvas

        # ── 布局常量（4 行：刷新频率 / 桌宠 / 完成音 / 重置音 + 按钮 + 警告） ──
        ST_TOP          = 10
        ST_BOTTOM       = H
        ST_PAD_X        = RO_GAP
        ST_W            = W - ST_PAD_X * 2
        ST_LBL_W        = 56             # 左侧标签宽度（"刷新频率"/"桌宠"/"完成音"/"重置音"）
        ST_RIGHT_LBL_W  = 26
        ST_VAL_W        = 22
        ST_GAP_X        = 6
        ST_KNOB_R       = 7
        ST_TRACK_H      = 4
        ST_ROW_H        = 22
        ST_ROW_GAP      = 4
        ST_WARN_H       = 14
        ST_BTN_H        = 20
        ST_BTN_GAP      = 8
        ST_BTN_WARN_GAP = 8
        ST_BOT_PAD      = 2
        ST_BTN_TOP_GAP  = 26     # 按钮↔上方行4 的视觉留白

        # 顶部往下排
        ST_row1_y       = ST_TOP                                  # 10  刷新频率
        ST_row2_y       = ST_row1_y + ST_ROW_H + ST_ROW_GAP       # 36  桌宠
        ST_row3_y       = ST_row2_y + ST_ROW_H + ST_ROW_GAP       # 62  完成音
        ST_row4_y       = ST_row3_y + ST_ROW_H + ST_ROW_GAP       # 88  重置音

        # 按钮在行4 下方，间距 ST_BTN_TOP_GAP；警告贴近面板下边
        ST_btn_top      = ST_row4_y + ST_ROW_H + ST_BTN_TOP_GAP   # 88+22+26=136
        ST_btn_y        = ST_btn_top + ST_BTN_H                    # 156 (anchor sw → 按钮底边)
        ST_warn_y       = ST_btn_y + ST_BTN_WARN_GAP               # 164
        # 校验：warn 底 = 164+14 = 178 ≤ H(180) - ST_BOT_PAD(2) ✓

        ST_left_x      = ST_PAD_X
        ST_slider_x    = ST_left_x + ST_LBL_W + ST_GAP_X
        ST_right_x     = W - ST_PAD_X - ST_RIGHT_LBL_W
        ST_val_x       = ST_right_x - ST_GAP_X - ST_VAL_W
        ST_slider_w    = ST_val_x - ST_slider_x - ST_GAP_X
        if ST_slider_w < 60:
            ST_slider_w = 60

        ST_current     = int(self.cfg.get("refresh_min", REFRESH_MIN_DEFAULT))
        ST_current     = max(REFRESH_MIN_MIN, min(REFRESH_MIN_MAX, ST_current))
        ST_var         = tk.IntVar(value=ST_current)
        ST_photo_ref   = {}   # 防止 PIL PhotoImage 被 GC

        ST_left_lbl = tk.Label(parent, text="刷新频率",
                               bg=PANEL, fg=WHITE,
                               font=("Segoe UI", 9, "bold"),
                               anchor="w")
        ST_left_lbl.place(x=ST_left_x, y=ST_row1_y,
                          width=ST_LBL_W, height=ST_ROW_H)

        ST_slider = tk.Canvas(parent, bg=PANEL, highlightthickness=0, bd=0,
                              cursor="hand2")
        ST_slider.place(x=ST_slider_x, y=ST_row1_y,
                        width=ST_slider_w, height=ST_ROW_H)

        # 当前值（贴在「分钟」前面，字号与「分钟」一致）
        ST_val_lbl = tk.Label(parent, text=str(ST_current),
                              bg=PANEL, fg=YELLOW,
                              font=("Segoe UI", 9, "bold"),
                              anchor="e")
        ST_val_lbl.place(x=ST_val_x, y=ST_row1_y,
                         width=ST_VAL_W, height=ST_ROW_H)

        ST_right_lbl = tk.Label(parent, text="分钟",
                                bg=PANEL, fg=WHITE,
                                font=("Segoe UI", 9, "bold"),
                                anchor="w")
        ST_right_lbl.place(x=ST_right_x, y=ST_row1_y,
                           width=ST_RIGHT_LBL_W, height=ST_ROW_H)

        # 贴底警告
        ST_warn = tk.Label(parent, text="",
                           bg=PANEL, fg=RED,
                           font=("Segoe UI", 8),
                           anchor="center")
        ST_warn.place(x=ST_PAD_X, y=ST_warn_y,
                      width=ST_W, height=ST_WARN_H)

        def _ST_val_to_x(v, w):
            """把数值映射到 knob 圆心 x 坐标（按当前画布宽度 w）。"""
            rng = REFRESH_MIN_MAX - REFRESH_MIN_MIN
            frac = (v - REFRESH_MIN_MIN) / rng if rng else 0
            return ST_KNOB_R + frac * (w - 2 * ST_KNOB_R)

        def _ST_x_to_val(x, w):
            """把鼠标 x 坐标映射回整数数值并 clamp 在 [MIN, MAX]。"""
            usable = w - 2 * ST_KNOB_R
            if usable <= 0:
                return REFRESH_MIN_MIN
            frac = (x - ST_KNOB_R) / usable
            frac = max(0.0, min(1.0, frac))
            return int(round(REFRESH_MIN_MIN + frac * (REFRESH_MIN_MAX - REFRESH_MIN_MIN)))

        def _ST_redraw(_=None):
            """用 PIL 超采样渲染滑块：圆角滑槽（半圆头）+ 已选段 + 白色圆形 knob。"""
            try:
                w = ST_slider.winfo_width()
                h = ST_slider.winfo_height()
            except Exception:
                return
            if w < 2 * ST_KNOB_R + 2 or h < 4:
                return
            S    = SCALE
            img  = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
            d    = ImageDraw.Draw(img)
            cy   = (h * S) // 2
            th   = ST_TRACK_H * S
            kr   = ST_KNOB_R * S
            half = th // 2
            # 滑槽底色（圆角矩形，半径=半高 → 两端半圆）
            d.rounded_rectangle(
                [(kr, cy - half), (w * S - kr, cy + half)],
                radius=half,
                fill=_rgba(ENTRY),
            )
            knob_x = int(_ST_val_to_x(ST_var.get(), w) * S)
            # 已选区段（同样半圆端）
            if knob_x > kr:
                d.rounded_rectangle(
                    [(kr, cy - half), (knob_x, cy + half)],
                    radius=half,
                    fill=_rgba(YELLOW),
                )
            # 白色圆形 knob，描一圈深色边缘提升清晰度
            d.ellipse(
                [(knob_x - kr, cy - kr), (knob_x + kr, cy + kr)],
                fill=_rgba(WHITE),
                outline=_rgba(BORDER),
                width=max(1, S),
            )
            img = img.resize((w, h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            ST_photo_ref["img"] = photo
            ST_slider.delete("all")
            ST_slider.create_image(0, 0, anchor="nw", image=photo)

        def _ST_update_val_warn():
            """更新值文字 + 警告文字（低于 REFRESH_MIN_WARN 显示提示）。"""
            v = ST_var.get()
            ST_val_lbl.config(text=str(v))
            if v < REFRESH_MIN_WARN:
                ST_warn.config(
                    text=f"⚠ 低于 {REFRESH_MIN_WARN} 分钟可能导致提取数据失败"
                )
            else:
                ST_warn.config(text="")

        def _ST_on_drag(e):
            """滑块鼠标按下/拖动：根据鼠标 x 更新数值并重绘。"""
            try:
                w = ST_slider.winfo_width()
            except Exception:
                return
            v = _ST_x_to_val(e.x, w)
            if v != ST_var.get():
                ST_var.set(v)
                _ST_redraw()
                _ST_update_val_warn()

        ST_slider.bind("<Configure>", _ST_redraw)
        ST_slider.bind("<Button-1>", _ST_on_drag)
        ST_slider.bind("<B1-Motion>", _ST_on_drag)
        _ST_update_val_warn()

        mascot_files = list_mascot_files() or ["(无)"]
        sound_files  = list_sound_files()  or ["(无)"]

        cur_mascot = self.cfg.get("mascot_file") or (
            mascot_files[0] if mascot_files and mascot_files[0] != "(无)" else "(无)"
        )
        ST_mascot_var = tk.StringVar(value=cur_mascot)
        ST_done_var   = tk.StringVar(value=self.cfg.get("done_sound", DONE_SOUND_DEFAULT))
        ST_reset_var  = tk.StringVar(value=self.cfg.get("reset_sound", RESET_SOUND_DEFAULT))
        ST_show_var   = tk.BooleanVar(value=bool(self.cfg.get("mascot_show", True)))

        def _style_om(om):
            """给 OptionMenu 套深色面板风格（按钮主体 + 下拉菜单）。"""
            om.configure(bg=ENTRY, fg=WHITE,
                         activebackground=BORDER, activeforeground=WHITE,
                         relief="flat", bd=0, highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=YELLOW,
                         font=("Segoe UI", 8), anchor="w", padx=6, pady=0)
            try:
                om["menu"].configure(
                    bg=ENTRY, fg=WHITE,
                    activebackground=YELLOW, activeforeground=WHITE,
                    bd=0, font=("Segoe UI", 8),
                )
            except Exception:
                pass

        # ── 3 个下拉框的左右对齐：统一 ST_combo_x / ST_combo_w ──
        ST_SWITCH_W  = 26
        ST_SWITCH_H  = 14
        ST_combo_x   = ST_left_x + ST_LBL_W + 2 + ST_SWITCH_W + ST_GAP_X
        ST_combo_w   = W - ST_PAD_X - ST_combo_x

        # row2: 桌宠 label + 显示开关 + GIF 下拉
        ST_mascot_lbl = tk.Label(parent, text="桌宠", bg=PANEL, fg=WHITE,
                                 font=("Segoe UI", 9, "bold"), anchor="w")
        ST_mascot_lbl.place(x=ST_left_x, y=ST_row2_y,
                            width=ST_LBL_W, height=ST_ROW_H)

        # 桌宠显示开关（pill 风格）：ON=GREEN，OFF=灰
        ST_switch_x = ST_left_x + ST_LBL_W + 2
        ST_switch_y = ST_row2_y + (ST_ROW_H - ST_SWITCH_H) // 2
        ST_show_sw = tk.Canvas(parent, bg=PANEL, highlightthickness=0,
                               bd=0, cursor="hand2")
        ST_show_sw.place(x=ST_switch_x, y=ST_switch_y,
                         width=ST_SWITCH_W, height=ST_SWITCH_H)

        def _ST_draw_switch():
            """绘制开关 pill：ON 绿底+knob 在右；OFF 灰底+knob 在左。"""
            try:
                ST_show_sw.delete("all")
            except Exception:
                return
            on = bool(ST_show_var.get())
            color = GREEN if on else "#475569"
            w, h = ST_SWITCH_W, ST_SWITCH_H
            r = h // 2
            ST_show_sw.create_oval(0, 0, h - 1, h - 1, fill=color, outline=color)
            ST_show_sw.create_oval(w - h, 0, w - 1, h - 1, fill=color, outline=color)
            ST_show_sw.create_rectangle(r, 0, w - r, h - 1, fill=color, outline=color)
            kx = (w - h + 2) if on else 2
            ST_show_sw.create_oval(kx, 2, kx + h - 4, h - 2,
                                   fill=WHITE, outline=WHITE)

        def _ST_toggle_switch(_e=None):
            ST_show_var.set(not ST_show_var.get())
            _ST_draw_switch()

        ST_show_sw.bind("<Button-1>", _ST_toggle_switch)
        _ST_draw_switch()

        # 桌宠 OptionMenu（与下方两个声音 OM 同 x 同宽）
        ST_mascot_om = tk.OptionMenu(parent, ST_mascot_var, *mascot_files)
        _style_om(ST_mascot_om)
        ST_mascot_om.place(x=ST_combo_x, y=ST_row2_y,
                           width=ST_combo_w, height=ST_ROW_H)

        # row3: 完成音
        ST_done_lbl = tk.Label(parent, text="完成音", bg=PANEL, fg=WHITE,
                               font=("Segoe UI", 9, "bold"), anchor="w")
        ST_done_lbl.place(x=ST_left_x, y=ST_row3_y,
                          width=ST_LBL_W, height=ST_ROW_H)
        ST_done_om = tk.OptionMenu(parent, ST_done_var, *sound_files)
        _style_om(ST_done_om)
        ST_done_om.place(x=ST_combo_x, y=ST_row3_y,
                         width=ST_combo_w, height=ST_ROW_H)

        # row4: 重置音
        ST_reset_lbl = tk.Label(parent, text="重置音", bg=PANEL, fg=WHITE,
                                font=("Segoe UI", 9, "bold"), anchor="w")
        ST_reset_lbl.place(x=ST_left_x, y=ST_row4_y,
                           width=ST_LBL_W, height=ST_ROW_H)
        ST_reset_om = tk.OptionMenu(parent, ST_reset_var, *sound_files)
        _style_om(ST_reset_om)
        ST_reset_om.place(x=ST_combo_x, y=ST_row4_y,
                          width=ST_combo_w, height=ST_ROW_H)

        # 底部两按钮：恢复默认（左）+ 保存（右）
        ST_btn_w   = (ST_W - ST_BTN_GAP) // 2
        ST_reset_x = ST_PAD_X
        ST_save_x  = ST_PAD_X + ST_btn_w + ST_BTN_GAP

        def _ST_reset():
            """恢复默认：刷新频率、桌宠、提示音都回到默认（需点保存才写入 cfg）。"""
            ST_var.set(REFRESH_MIN_DEFAULT)
            _ST_redraw()
            _ST_update_val_warn()
            if MASCOT_PRIMARY_NAME in mascot_files:
                ST_mascot_var.set(MASCOT_PRIMARY_NAME)
            elif mascot_files:
                ST_mascot_var.set(mascot_files[0])
            if DONE_SOUND_DEFAULT in sound_files:
                ST_done_var.set(DONE_SOUND_DEFAULT)
            elif sound_files:
                ST_done_var.set(sound_files[0])
            if RESET_SOUND_DEFAULT in sound_files:
                ST_reset_var.set(RESET_SOUND_DEFAULT)
            elif sound_files:
                ST_reset_var.set(sound_files[0])
            ST_show_var.set(True)
            _ST_draw_switch()

        def _ST_save():
            """SETTINGS 保存按钮回调：写入 refresh_min / mascot_file / done_sound / reset_sound；
            重置周期刷新定时器；桌宠若变了立刻热重载。"""
            ST_new = int(ST_var.get())
            ST_new = max(REFRESH_MIN_MIN, min(REFRESH_MIN_MAX, ST_new))
            self.cfg["refresh_min"] = ST_new

            new_mascot = ST_mascot_var.get()
            new_done   = ST_done_var.get()
            new_reset  = ST_reset_var.get()
            new_show   = bool(ST_show_var.get())
            mascot_changed = False
            if new_mascot and new_mascot != "(无)":
                if new_mascot != self.cfg.get("mascot_file"):
                    mascot_changed = True
                self.cfg["mascot_file"] = new_mascot
            if new_done and new_done != "(无)":
                self.cfg["done_sound"] = new_done
            if new_reset and new_reset != "(无)":
                self.cfg["reset_sound"] = new_reset
            show_changed = (new_show != bool(self.cfg.get("mascot_show", True)))
            self.cfg["mascot_show"] = new_show

            save_cfg(self.cfg)
            self._toggle_settings()
            if self._refresh_after_id is not None:
                try: self.root.after_cancel(self._refresh_after_id)
                except: pass
                self._refresh_after_id = None
            if self.cfg.get("session_key") and not self.loading:
                self._refresh_after_id = self.root.after(
                    ST_new * 60 * 1000, self._refresh
                )
            delay = ACCOUNT_ANIM_MS * (ACCOUNT_BG_ANIM_STEPS + ACCOUNT_PANEL_ANIM_STEPS) + 20
            if show_changed:
                self.root.after(delay, self._apply_mascot_visibility)
            elif mascot_changed:
                # 等面板关闭动画结束后再热重载，避免视觉混淆
                self.root.after(delay, self._reload_mascot)

        ST_reset_btn = tk.Button(
            parent,
            text="恢复默认",
            command=_ST_reset,
            bg=ENTRY, fg=WHITE,
            activebackground=BORDER,
            activeforeground=WHITE,
            relief="flat", bd=0,
            padx=10, pady=2,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
        )
        ST_reset_btn.place(x=ST_reset_x, y=ST_btn_y, anchor="sw",
                           width=ST_btn_w, height=ST_BTN_H)

        ST_save_btn = tk.Button(
            parent,
            text="保  存",
            command=_ST_save,
            bg=GREEN, fg=WHITE,
            activebackground=YELLOW,
            activeforeground=WHITE,
            relief="flat", bd=0,
            padx=10, pady=2,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
        )
        ST_save_btn.place(x=ST_save_x, y=ST_btn_y, anchor="sw",
                          width=ST_btn_w, height=ST_BTN_H)

        self._panel_widgets = [
            (ST_left_lbl,   ST_left_x,     ST_row1_y,           ST_LBL_W,       ST_ROW_H),
            (ST_slider,     ST_slider_x,   ST_row1_y,           ST_slider_w,    ST_ROW_H),
            (ST_val_lbl,    ST_val_x,      ST_row1_y,           ST_VAL_W,       ST_ROW_H),
            (ST_right_lbl,  ST_right_x,    ST_row1_y,           ST_RIGHT_LBL_W, ST_ROW_H),
            (ST_mascot_lbl, ST_left_x,     ST_row2_y,           ST_LBL_W,       ST_ROW_H),
            (ST_show_sw,    ST_switch_x,   ST_switch_y,         ST_SWITCH_W,    ST_SWITCH_H),
            (ST_mascot_om,  ST_combo_x,    ST_row2_y,           ST_combo_w,     ST_ROW_H),
            (ST_done_lbl,   ST_left_x,     ST_row3_y,           ST_LBL_W,       ST_ROW_H),
            (ST_done_om,    ST_combo_x,    ST_row3_y,           ST_combo_w,     ST_ROW_H),
            (ST_reset_lbl,  ST_left_x,     ST_row4_y,           ST_LBL_W,       ST_ROW_H),
            (ST_reset_om,   ST_combo_x,    ST_row4_y,           ST_combo_w,     ST_ROW_H),
            (ST_reset_btn,  ST_reset_x,    ST_btn_top,          ST_btn_w,       ST_BTN_H),
            (ST_save_btn,   ST_save_x,     ST_btn_top,          ST_btn_w,       ST_BTN_H),
            (ST_warn,       ST_PAD_X,      ST_warn_y,           ST_W,           ST_WARN_H),
        ]

        # 桌宠下拉的菜单 hover → 预览
        # <Map>=菜单弹出时建预览窗；<<MenuSelect>>=hover 在哪个 entry 上；
        # <Unmap>=菜单关闭时销毁预览
        ST_mascot_menu = ST_mascot_om["menu"]

        def _on_menu_map(_e=None):
            """桌宠下拉弹出：建预览悬浮窗 + 预览当前活动项。"""
            self._build_preview_window()
            # 弹出瞬间预览当前活动项（一般是当前选中项）
            try:
                idx = ST_mascot_menu.index("active")
                if idx != "none" and idx is not None:
                    self._load_preview_gif(ST_mascot_menu.entrycget(idx, "label"))
            except Exception:
                pass

        def _on_menu_select(_e=None):
            """桌宠下拉 hover 切换：读当前 active entry 名字喂给预览。"""
            try:
                idx = ST_mascot_menu.index("active")
                if idx == "none" or idx is None:
                    return
                name = ST_mascot_menu.entrycget(idx, "label")
            except Exception:
                return
            if self._preview_top is None:
                self._build_preview_window()
            self._load_preview_gif(name)

        def _on_menu_unmap(_e=None):
            """桌宠下拉关闭：销毁预览悬浮窗。"""
            self._destroy_preview()

        ST_mascot_menu.bind("<Map>",          _on_menu_map)
        ST_mascot_menu.bind("<<MenuSelect>>", _on_menu_select)
        ST_mascot_menu.bind("<Unmap>",        _on_menu_unmap)

        # 完成音 / 重置音 下拉 hover → 单次试听对应文件；切换时自动停掉上一段
        def _mk_sound_hover(om):
            """给一个声音 OptionMenu 装上 hover 单次试听 + 关闭即停 的能力。"""
            menu = om["menu"]
            last = [None]   # 记录上一次试听的文件名，避免反复 hover 同一项重播

            def _on_select(_e=None):
                """hover 切换：active 项变了就 stop 旧的、play 新的一次。"""
                try:
                    idx = menu.index("active")
                    if idx == "none" or idx is None:
                        return
                    name = menu.entrycget(idx, "label")
                except Exception:
                    return
                if not name or name == "(无)" or name == last[0]:
                    return
                last[0] = name
                play_preview_sound(SOUND_DIR / name)

            def _on_unmap(_e=None):
                """声音下拉关闭：清空 last 记录并 stop 当前试听。"""
                last[0] = None
                stop_preview_sound()

            menu.bind("<<MenuSelect>>", _on_select)
            menu.bind("<Unmap>",        _on_unmap)

        _mk_sound_hover(ST_done_om)
        _mk_sound_hover(ST_reset_om)
        self._panel_cx = W // 2
        self._panel_cy = (ST_TOP + ST_BOTTOM) // 2

    # ── 5-hour 用尽倒计时 ────────────────────────────────
    def _tick_overlay(self):
        """5-hour 倒计时下一帧；到 0 自动刷新。"""
        self._overlay_after_id = None
        reset_at = self.data.get("five_reset_at")
        if reset_at is None:
            return
        remaining = int((reset_at - datetime.now(timezone.utc)).total_seconds())
        if remaining <= 0:
            # 重置时间到达：播提示音 + 清掉当前 pct 数据并触发一次刷新
            play_sound_async(SOUND_DIR / self.cfg.get("reset_sound", RESET_SOUND_DEFAULT))
            self.data["five_pct"] = None
            self.data["five_reset_at"] = None
            self.data["five_reset"] = ""
            self.draw()
            self._refresh()
        else:
            self.draw()

    # ── 绘制主区域 ─────────────────────────────────────────
    def draw(self):
        """重绘主画布：背景双环 + 顶栏图标/状态文字 + 双环中央数字/重置时间/用尽覆盖。"""
        c = self.cv

        five_pct      = self.data.get("five_pct")
        seven_pct     = self.data.get("seven_pct")
        five_reset    = self.data.get("five_reset", "")
        seven_reset   = self.data.get("seven_reset", "")
        five_reset_at = self.data.get("five_reset_at")
        err           = self.data.get("error")

        # 判断 5-hour 是否用尽且未到重置时间
        five_overlay = False
        remaining = 0
        if (five_pct is not None and five_pct >= 0.995
                and five_reset_at is not None):
            remaining = int((five_reset_at - datetime.now(timezone.utc)).total_seconds())
            if remaining > 0:
                five_overlay = True

        # 取消旧的倒计时定时器
        if self._overlay_after_id is not None:
            try: self.root.after_cancel(self._overlay_after_id)
            except: pass
            self._overlay_after_id = None

        scale = COMPACT_SCALE if self._compact else 1.0
        cur_w = COMPACT_W if self._compact else W
        cur_h = COMPACT_H if self._compact else H
        new_photo = render_bg(cur_w, cur_h, five_pct, seven_pct,
                              five_overlay=five_overlay,
                              compact=self._compact,
                              scale=scale)
        c.delete("rings")
        self._photo = new_photo
        c.create_image(0, 0, anchor="nw", image=self._photo, tags="rings")

        # 紧凑模式仅显示左环；顶栏图标 / 状态文字 / 右环全部跳过
        if not self._compact:
            if self._claude_icon:
                c.create_image(ICON_GAP + ICON_SZ, ICON_SZ, anchor="center",
                               image=self._claude_icon, tags="rings")

            if err:
                msg, col = f"⚠ {err[:22]}", RED
            elif self.loading:
                msg, col = "读取中…", MUTED
            elif not self.cfg.get("session_key"):
                msg, col = "点击 ⚙ 设置认证", RED
            else:
                msg, col = datetime.now().strftime("%H:%M") + " 更新", MUTED
            c.create_text(ICON_GAP + ICON_SZ * 2, ICON_SZ, text=msg, fill=col, anchor="w",
                          font=("Segoe UI", 9), tags="rings")

            icon_font = ("Segoe UI Symbol", 10)
            icons = [
                (W - ICON_GAP * 3 - ICON_SZ * 3, "A", "btn_a"),
                (W - ICON_GAP * 2 - ICON_SZ * 2, "S", "btn_s"),
                (W - ICON_GAP - ICON_SZ, "✕", "btn_q"),
            ]
            for x, txt, tag in icons:
                normal, _hot = self._btn_icons.get(tag, (None, None))
                if normal is not None:
                    c.create_image(x, ICON_SZ, anchor="center",
                                   image=normal, tags=(tag, "rings"))
                else:
                    c.create_text(x, ICON_SZ, text=txt, fill=MUTED,
                                  font=icon_font, tags=(tag, "rings"))

        # 紧凑模式：环居中于画布；文字额外放大 COMPACT_TEXT_SCALE
        if self._compact:
            sx_left = cur_w / 2
            sy_pos  = cur_h / 2
            text_factor = scale * COMPACT_TEXT_SCALE
        else:
            sx_left = CX1 * scale
            sy_pos  = CY  * scale
            text_factor = scale
        y_off    = 20 * text_factor
        right_cx = cur_w - sx_left
        title_sz = max(6, int(round(10 * text_factor)))
        pct_sz   = max(8, int(round(16 * text_factor)))
        reset_sz = max(6, int(round(9  * text_factor)))
        ov_title_sz = max(6, int(round(8  * text_factor)))
        ov_big_sz   = max(8, int(round(22 * text_factor)))
        ov_med_sz   = max(8, int(round(18 * text_factor)))

        def _ring_text(cx, title, pct, reset_txt):
            """在一个环中央绘制三行文字：标题 / 百分比 / 重置倒计时（按 scale 等比）。"""
            col = ring_color(pct) if pct is not None else MUTED
            pct_txt = (
                f"{pct*100:.0f}%" if pct is not None
                else ("…" if self.loading else "--")
            )
            c.create_text(cx, sy_pos - y_off, text=title,
                          fill=WHITE, font=("Segoe UI", title_sz, "bold"), tags="rings")
            c.create_text(cx, sy_pos, text=pct_txt,
                          fill=col, font=("Segoe UI", pct_sz, "bold"),
                          tags="rings")
            if reset_txt:
                c.create_text(cx, sy_pos + y_off, text=reset_txt,
                              fill=WHITE, font=("Segoe UI", reset_sz), tags="rings")

        if self._left_ring_hover and not self.loading:
            ref_icon = self._refresh_small if self._compact else self._refresh_big
            if ref_icon is not None:
                c.create_image(sx_left, sy_pos, anchor="center",
                               image=ref_icon, tags="rings")
            else:
                c.create_text(sx_left, sy_pos, text="⟳", fill=WHITE,
                              font=("Segoe UI Symbol", max(10, int(24 * scale)), "bold"),
                              tags="rings")
        elif five_overlay:
            # 倒计时覆盖：放大显示，不足 5 分钟则读秒
            if remaining < 300:
                m_, s_ = divmod(remaining, 60)
                big_txt = f"{m_}:{s_:02d}"
                big_font = ("Segoe UI", ov_big_sz, "bold")
            else:
                h_, rem = divmod(remaining, 3600)
                m_ = rem // 60
                big_txt = f"{h_}h {m_:02d}m" if h_ else f"{m_}m"
                big_font = ("Segoe UI", ov_med_sz, "bold")
            c.create_text(sx_left, sy_pos - 16 * text_factor, text="重置倒计时",
                          fill=WHITE, font=("Segoe UI", ov_title_sz), tags="rings")
            c.create_text(sx_left, sy_pos + 8 * text_factor, text=big_txt,
                          fill=YELLOW, font=big_font, tags="rings")
            self._overlay_after_id = self.root.after(1000, self._tick_overlay)
        else:
            _ring_text(sx_left, "5-Hour", five_pct, five_reset)
        if not self._compact:
            _ring_text(right_cx, "Weekly", seven_pct, seven_reset)

    def run(self):
        """启动 Tk mainloop（程序入口）。"""
        self.root.mainloop()


if __name__ == "__main__":
    Widget().run()
