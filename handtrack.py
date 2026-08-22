"""
Retro Lens - Real-time Hand Gesture Filter Pipeline
"""

from dataclasses import dataclass
import ctypes
from ctypes import wintypes
import math
import os
import random
import threading
import time
from typing import Dict, List, Tuple, Callable, Optional
import urllib.request

import cv2
import mediapipe as mp
import numpy as np


@dataclass
class PipelineConfig:
    cam_index: int = 0
    frame_width: int = 1280
    frame_height: int = 720
    pinch_threshold_px: float = 42.0
    screenshot_threshold_px: float = 45.0
    pinch_hold_frames: int = 2
    screenshot_hold_frames: int = 2
    filter_cooldown_sec: float = 0.55
    screenshot_cooldown_sec: float = 1.3
    mode_cooldown_sec: float = 0.4
    fist_dist_threshold_px: float = 75.0


class ScreenCaptureHelper:
    """
    Helper untuk mengambil screenshot seluruh layar (Desktop) di Windows secara ultra-cepat via GDI ctypes.
    """
    @staticmethod
    def capture_desktop() -> Optional[np.ndarray]:
        try:
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            
            # Pastikan DPI-aware agar selalu menangkap resolusi Full HD asli (1920x1080 / 4K)
            try:
                user32.SetProcessDpiAwarenessContext(-4)
            except Exception:
                try:
                    user32.SetProcessDPIAware()
                except Exception:
                    pass

            w = user32.GetSystemMetrics(0)
            h = user32.GetSystemMetrics(1)
            
            hdc_screen = user32.GetDC(0)
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbm = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
            gdi32.SelectObject(hdc_mem, hbm)
            gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, 0, 0, 0x00CC0020)
            
            gdi32.GetDIBits.argtypes = [
                wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT
            ]
            gdi32.GetDIBits.restype = ctypes.c_int
            
            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ('biSize', wintypes.DWORD),
                    ('biWidth', wintypes.LONG),
                    ('biHeight', wintypes.LONG),
                    ('biPlanes', wintypes.WORD),
                    ('biBitCount', wintypes.WORD),
                    ('biCompression', wintypes.DWORD),
                    ('biSizeImage', wintypes.DWORD),
                    ('biXPelsPerMeter', wintypes.LONG),
                    ('biYPelsPerMeter', wintypes.LONG),
                    ('biClrUsed', wintypes.DWORD),
                    ('biClrImportant', wintypes.DWORD)
                ]
            
            bi = BITMAPINFOHEADER()
            bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bi.biWidth = w
            bi.biHeight = -h  # top-down DIB
            bi.biPlanes = 1
            bi.biBitCount = 32
            bi.biCompression = 0
            
            buffer = np.zeros((h, w, 4), dtype=np.uint8)
            gdi32.GetDIBits(hdc_mem, hbm, 0, h, buffer.ctypes.data_as(ctypes.c_void_p), ctypes.byref(bi), 0)
            
            gdi32.DeleteObject(hbm)
            gdi32.DeleteDC(hdc_mem)
            user32.ReleaseDC(0, hdc_screen)
            return cv2.cvtColor(buffer, cv2.COLOR_BGRA2BGR)
        except Exception:
            return None

    @staticmethod
    def play_shutter_sound() -> None:
        def _sound():
            try:
                import winsound
                winsound.Beep(1400, 60)
                winsound.Beep(1900, 80)
            except Exception:
                pass
        threading.Thread(target=_sound, daemon=True).start()


class FilterBank:
    @staticmethod
    def anime_style(roi: np.ndarray) -> np.ndarray:
        """
        Filter Makoto Shinkai / Anime Movie Aesthetic:
        - Ilustrasi 2D halus tanpa noise bintik (Edge-Preserving Domain Transform)
        - Cel Shading kuantisasi warna ala kartun Jepang
        - Soft Manga Ink Outline (garis tinta halus presisi)
        - Vibrant warm pastel grading & ethereal anime bloom diffusion
        """
        h, w = roi.shape[:2]
        if h < 4 or w < 4: return roi
        
        # 1. Downscale 0.5x -> Edge-Preserving Filter -> Upscale untuk 60 FPS real-time
        scale_w, scale_h = max(2, w // 2), max(2, h // 2)
        small = cv2.resize(roi, (scale_w, scale_h), interpolation=cv2.INTER_LINEAR)
        
        # Edge-Preserving Filter (Menghilangkan noise kulit & tekstur fotografi jadi lukisan 2D)
        smooth_small = cv2.edgePreservingFilter(small, flags=1, sigma_s=45, sigma_r=0.35)
        smooth = cv2.resize(smooth_small, (w, h), interpolation=cv2.INTER_LINEAR)
        
        # 2. Cel-Shading Tone Curve (Makoto Shinkai & Kyoto Animation Cel Look)
        lut = np.zeros(256, dtype=np.uint8)
        for i in range(256):
            if i < 60:
                lut[i] = int(i * 0.70)
            elif i < 150:
                lut[i] = int(42 + (i - 60) * 1.15)
            else:
                lut[i] = min(255, int(145 + (i - 150) * 0.95))
        cel = cv2.LUT(smooth, lut)
        
        # 3. Vibrant Anime Color Grading (Pastel Warm Tones & Radiant Skies)
        hsv = cv2.cvtColor(cel, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.38 + 12, 0, 255) # Saturasi warna hidup
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.06 + 4, 0, 255)  # Kecerahan
        color_graded = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
        
        # 4. Clean Manga Line Art (Difference of Gaussians untuk garis pensil manga halus)
        gray = cv2.cvtColor(smooth, cv2.COLOR_BGR2GRAY)
        blur1 = cv2.GaussianBlur(gray, (3, 3), 0)
        blur2 = cv2.GaussianBlur(gray, (9, 9), 0)
        dog = cv2.subtract(blur2, blur1)
        _, edges = cv2.threshold(dog, 8, 255, cv2.THRESH_BINARY)
        
        inv_edges = cv2.bitwise_not(edges)
        ink_mask = (inv_edges == 0)
        color_graded[ink_mask] = (35, 25, 45) # Dark Charcoal BGR
        
        # 5. Ethereal Anime Bloom / Lens Glow
        blur_bloom = cv2.GaussianBlur(color_graded, (19, 19), 0)
        anime_final = cv2.addWeighted(color_graded, 0.84, blur_bloom, 0.22, 0)
        
        return anime_final

    @staticmethod
    def cyberpunk_neon(roi: np.ndarray) -> np.ndarray:
        h, w = roi.shape[:2]
        if h < 2 or w < 2: return roi
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 35, 110)
        kernel = np.ones((3, 3), np.uint8)
        glow = cv2.dilate(edges, kernel, iterations=1)
        
        out = np.zeros_like(roi)
        dark_bg = (gray // 5).astype(np.uint8)
        out[:, :, 0] = dark_bg * 2
        out[:, :, 2] = dark_bg
        out[glow > 0] = (255, 220, 0)      # Cyan glow (BGR)
        out[edges > 0] = (220, 40, 255)    # Magenta core line (BGR)
        return out

    @staticmethod
    def matrix_code(roi: np.ndarray) -> np.ndarray:
        h, w = roi.shape[:2]
        if h < 2 or w < 2: return roi
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 40, 130)
        out = np.zeros_like(roi)
        out[:, :, 1] = (gray * 0.75).astype(np.uint8)
        out[edges > 0, 1] = 255
        out[edges > 0, 0] = 60
        scan = (np.sin(np.arange(h) * 0.35 + time.time() * 6.0) * 30 + 225).astype(np.uint8)
        out[:, :, 1] = np.minimum(out[:, :, 1], scan[:, None])
        return out

    @staticmethod
    def vaporwave_80s(roi: np.ndarray) -> np.ndarray:
        h, w = roi.shape[:2]
        if h < 2 or w < 2: return roi
        b, g, r = cv2.split(roi)
        shift = int(np.sin(time.time() * 4.0) * 3 + 6)
        r = np.roll(r, shift, axis=1)
        b = np.roll(b, -shift, axis=1)
        shifted = cv2.merge([b, g, r])
        gray = cv2.cvtColor(shifted, cv2.COLOR_BGR2GRAY)
        lut = cv2.applyColorMap(gray, cv2.COLORMAP_MAGMA)
        return cv2.addWeighted(shifted, 0.45, lut, 0.55, 0)

    @staticmethod
    def hologram(roi: np.ndarray) -> np.ndarray:
        h, w = roi.shape[:2]
        if h < 2 or w < 2: return roi
        
        # 1. Base Holographic Luminescence & Cyan Grading
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 35, 115)
        
        holo = np.zeros_like(roi)
        holo[:, :, 0] = cv2.add((gray * 0.92).astype(np.uint8), 65)   # Blue channel
        holo[:, :, 1] = cv2.add((gray * 0.78).astype(np.uint8), 35)   # Green channel
        holo[:, :, 2] = (gray * 0.20).astype(np.uint8)                # Red channel
        
        # 2. Glowing Cyan Highlights on Edges
        holo[edges > 0] = (255, 235, 140)
        
        # 3. Dynamic TV Static Snow / "Semut-semut TV Rusak"
        noise = np.random.randint(0, 65, (h, w), dtype=np.uint8)
        holo[:, :, 0] = cv2.add(holo[:, :, 0], noise)
        holo[:, :, 1] = cv2.add(holo[:, :, 1], (noise * 0.8).astype(np.uint8))
        
        # Salt & Pepper static particles
        static_snow = np.random.random((h, w)) < 0.08
        if np.any(static_snow):
            holo[static_snow] = np.random.randint(180, 255, (np.count_nonzero(static_snow), 3), dtype=np.uint8)
        
        # 4. CRT Horizontal Scanlines
        scanlines = np.ones((h, 1, 1), dtype=np.float32)
        scanlines[::2] = 0.65
        scanlines[1::4] = 0.85
        holo = (holo.astype(np.float32) * scanlines).astype(np.uint8)
        
        # 5. Rolling Tracking Scan Bar (Sinyal TV Meluncur)
        t = time.time()
        scan_bar = int((t * 110) % h)
        bar_h = min(8, h - scan_bar)
        if bar_h > 0:
            holo[scan_bar : scan_bar + bar_h, :] = cv2.add(holo[scan_bar : scan_bar + bar_h, :], 75)
            
        # 6. Random Horizontal Glitch Tears
        for _ in range(2):
            if random.random() < 0.65:
                y_glitch = random.randint(0, h - 3)
                gh = random.randint(1, 3)
                shift = random.randint(-16, 16)
                holo[y_glitch : y_glitch + gh, :] = np.roll(holo[y_glitch : y_glitch + gh, :], shift, axis=1)
                holo[y_glitch : y_glitch + 1, :] = np.random.randint(120, 255, (1, w, 3), dtype=np.uint8)

        # 7. Subtle CRT Luminance Flicker
        flicker = 1.0 + np.sin(t * 45.0) * 0.04
        if flicker != 1.0:
            holo = cv2.convertScaleAbs(holo, alpha=flicker, beta=0)

        return holo

    @staticmethod
    def tv_static_nosignal(roi: np.ndarray) -> np.ndarray:
        """Filter TV Tabung Rusak / No Signal Analog Snow (Semut TV Pekat)."""
        h, w = roi.shape[:2]
        if h < 2 or w < 2: return roi
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        snow = np.random.randint(20, 245, (h, w), dtype=np.uint8)
        tv = cv2.addWeighted(gray, 0.45, snow, 0.55, 0)
        
        scan = np.ones((h, 1), dtype=np.float32)
        scan[::2] = 0.60
        tv = (tv.astype(np.float32) * scan).astype(np.uint8)
        
        t = time.time()
        roll_y = int((t * 140) % h)
        rh = min(14, h - roll_y)
        if rh > 0:
            tv[roll_y : roll_y + rh, :] = np.random.randint(160, 255, (rh, w), dtype=np.uint8)
            
        for _ in range(3):
            if random.random() < 0.8:
                gy = random.randint(0, h - 2)
                tv[gy : gy + 2, :] = np.roll(tv[gy : gy + 2, :], random.randint(-25, 25))
                
        out = cv2.cvtColor(tv, cv2.COLOR_GRAY2BGR)
        out[:, :, 0] = cv2.add(out[:, :, 0], 15)  # Cold blue tint
        out[:, :, 1] = cv2.add(out[:, :, 1], 10)  # Green tint
        return out

    @staticmethod
    def vintage_1920_film(roi: np.ndarray) -> np.ndarray:
        """Filter Film Bisu Klasik 1920s dengan goresan proyektor dan sepia tua."""
        h, w = roi.shape[:2]
        if h < 2 or w < 2: return roi
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        # Sepia tone grading
        sepia = np.zeros_like(roi)
        sepia[:, :, 0] = (gray * 0.50).astype(np.uint8)  # Blue
        sepia[:, :, 1] = (gray * 0.70).astype(np.uint8)  # Green
        sepia[:, :, 2] = (gray * 0.90).astype(np.uint8)  # Red
        
        # Dust specks
        dust = np.random.random((h, w)) < 0.015
        if np.any(dust):
            sepia[dust] = [230, 230, 230]
        
        # Vertical film scratch lines
        if random.random() < 0.7:
            x_scratch = random.randint(0, w - 1)
            sepia[:, x_scratch : min(w, x_scratch + 1)] = 230
            
        # Projector shutter flicker
        flicker = 1.0 + random.uniform(-0.10, 0.10)
        return cv2.convertScaleAbs(sepia, alpha=flicker, beta=random.randint(-5, 5))

    @staticmethod
    def kaleidoscope_mirror(roi: np.ndarray) -> np.ndarray:
        """Filter Kaleidoskop 4 Kuadran Simetris."""
        h, w = roi.shape[:2]
        if h < 4 or w < 4: return roi
        half_h, half_w = h // 2, w // 2
        top_left = roi[:half_h, :half_w]
        top_right = cv2.flip(top_left, 1)
        top = np.hstack([top_left, top_right])
        bottom = cv2.flip(top, 0)
        full = np.vstack([top, bottom])
        return cv2.resize(full, (w, h))

    @staticmethod
    def psychedelic_aura(roi: np.ndarray) -> np.ndarray:
        """Filter Aura Psychedelic dengan Solarized Rainbow Color Cycling."""
        h, w = roi.shape[:2]
        if h < 2 or w < 2: return roi
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        shift_hue = int((time.time() * 60) % 180)
        hsv[:, :, 0] = (hsv[:, :, 0].astype(np.int16) + shift_hue) % 180
        hsv[:, :, 1] = cv2.add(hsv[:, :, 1], 60)  # High saturation
        # Solarize value
        hsv[:, :, 2] = np.where(hsv[:, :, 2] > 128, 255 - hsv[:, :, 2], hsv[:, :, 2] * 2)
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)

    @staticmethod
    def laser_wireframe(roi: np.ndarray) -> np.ndarray:
        """Filter Wireframe Garis Laser Neon pada latar belakang hitam pekat."""
        h, w = roi.shape[:2]
        if h < 2 or w < 2: return roi
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        edges1 = cv2.Canny(gray, 30, 90)
        edges2 = cv2.Canny(gray, 90, 180)
        
        out = np.zeros_like(roi)
        out[edges1 > 0] = (255, 180, 0)    # Cyan electric
        out[edges2 > 0] = (0, 220, 255)    # Gold glow
        return out

    @staticmethod
    def fire_plasma(roi: np.ndarray) -> np.ndarray:
        h, w = roi.shape[:2]
        if h < 2 or w < 2: return roi
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        x_c, y_c = np.meshgrid(np.arange(w), np.arange(h))
        turb = (np.sin(x_c * 0.04 + time.time() * 4.0) * 15 + np.cos(y_c * 0.04) * 15).astype(np.int16)
        mod_gray = np.clip(gray.astype(np.int16) + turb, 0, 255).astype(np.uint8)
        return cv2.applyColorMap(mod_gray, cv2.COLORMAP_INFERNO)

    @staticmethod
    def night_vision(roi: np.ndarray) -> np.ndarray:
        h, w = roi.shape[:2]
        if h < 2 or w < 2: return roi
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        eq = cv2.equalizeHist(gray)
        out = np.zeros_like(roi)
        out[:, :, 1] = eq
        out[:, :, 0] = (eq // 5)
        noise = np.random.randint(0, 25, (h, w), dtype=np.uint8)
        out[:, :, 1] = cv2.add(out[:, :, 1], noise)
        return out

    @staticmethod
    def comic_pop_art(roi: np.ndarray) -> np.ndarray:
        h, w = roi.shape[:2]
        if h < 2 or w < 2: return roi
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        edges = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 8)
        color = cv2.bilateralFilter(roi, 9, 200, 200)
        color = (color // 48) * 48
        return cv2.bitwise_and(color, cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR))

    @staticmethod
    def dual_tone(roi: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 110, 255, cv2.THRESH_BINARY)
        out = np.zeros_like(roi)
        out[mask == 255] = (10, 140, 255)   # Amber Gold
        out[mask == 0] = (180, 30, 220)     # Neon Violet
        return out

    @staticmethod
    def thermal(roi: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        eq = cv2.equalizeHist(gray)
        return cv2.applyColorMap(eq, cv2.COLORMAP_JET)

    @staticmethod
    def sketch(roi: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        inv = 255 - gray
        blur = cv2.GaussianBlur(inv, (21, 21), 0)
        sketch = cv2.divide(gray, 255 - blur, scale=256)
        return cv2.cvtColor(sketch, cv2.COLOR_GRAY2BGR)

    @staticmethod
    def pixelate(roi: np.ndarray, block_size: int = 14) -> np.ndarray:
        h, w = roi.shape[:2]
        if h < 2 or w < 2: return roi
        small = cv2.resize(roi, (max(1, w // block_size), max(1, h // block_size)), interpolation=cv2.INTER_LINEAR)
        return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)

    @staticmethod
    def glitch(roi: np.ndarray) -> np.ndarray:
        h, w = roi.shape[:2]
        if h < 2 or w < 2: return roi
        b, g, r = cv2.split(roi)
        shift = random.randint(6, 16)
        r = np.roll(r, shift, axis=1)
        b = np.roll(b, -shift, axis=1)
        out = cv2.merge([b, g, r])
        for _ in range(3):
            y = random.randint(0, h - 1)
            out[y : y + 2, :] = np.random.randint(0, 255, (min(2, h - y), w, 3), dtype=np.uint8)
        return out

    @staticmethod
    def invert(roi: np.ndarray) -> np.ndarray:
        return 255 - roi

    @staticmethod
    def red_channel(roi: np.ndarray) -> np.ndarray:
        b, g, r = cv2.split(roi)
        zeros = np.zeros_like(b)
        return cv2.merge([zeros, zeros, r])

    @staticmethod
    def edge(roi: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 60, 150)
        colored = cv2.applyColorMap(edges, cv2.COLORMAP_SUMMER)
        return cv2.bitwise_and(colored, colored, mask=edges)

    @staticmethod
    def blur(roi: np.ndarray) -> np.ndarray:
        return cv2.GaussianBlur(roi, (25, 25), 0)

    @staticmethod
    def cartoon(roi: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray_blur = cv2.medianBlur(gray, 5)
        edges = cv2.adaptiveThreshold(gray_blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 9)
        color = cv2.bilateralFilter(roi, 9, 250, 250)
        return cv2.bitwise_and(color, cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR))

    @staticmethod
    def rainbow_wave(roi: np.ndarray) -> np.ndarray:
        h, w = roi.shape[:2]
        t = time.time() * 5.0
        x_coords, y_coords = np.meshgrid(np.arange(w), np.arange(h))
        pattern = np.sin((x_coords + y_coords) * 0.05 + t) * 127 + 128
        rainbow = cv2.applyColorMap(pattern.astype(np.uint8), cv2.COLORMAP_HSV)
        return cv2.addWeighted(roi, 0.35, rainbow, 0.65, 0)


class GeometryUtils:
    @staticmethod
    def euclidean_dist(p1: Tuple[int, int], p2: Tuple[int, int]) -> float:
        return float(np.hypot(p1[0] - p2[0], p1[1] - p2[1]))

    @staticmethod
    def is_hand_rotated(thumb: Tuple[int, int], index: Tuple[int, int]) -> bool:
        dx, dy = index[0] - thumb[0], index[1] - thumb[1]
        return (dy > 25) or (abs(dx) > abs(dy) * 1.1)

    @staticmethod
    def sort_quad_clean(pts: List[Tuple[int, int]]) -> np.ndarray:
        arr = np.array(pts, dtype=np.float32)
        x_sorted = arr[np.argsort(arr[:, 0]), :]
        leftmost = x_sorted[:2, :][np.argsort(x_sorted[:2, 1]), :]
        rightmost = x_sorted[2:, :][np.argsort(x_sorted[2:, 1]), :]
        return np.array([leftmost[0], rightmost[0], rightmost[1], leftmost[1]], dtype=np.int32)

    @staticmethod
    def sort_quad_bowtie(pts: List[Tuple[int, int]]) -> np.ndarray:
        arr = np.array(pts, dtype=np.float32)
        x_sorted = arr[np.argsort(arr[:, 0]), :]
        leftmost = x_sorted[:2, :][np.argsort(x_sorted[:2, 1]), :]
        rightmost = x_sorted[2:, :][np.argsort(x_sorted[2:, 1]), :]
        return np.array([leftmost[0], rightmost[1], rightmost[0], leftmost[1]], dtype=np.int32)


class HandDetector:
    """
    Adapter detektor tangan universal.
    Mendukung MediaPipe modern Tasks API (MediaPipe 0.10.15+ / 1.0+)
    serta legacy solutions API jika tersedia.
    Menggunakan VIDEO mode untuk temporal tracking yang stabil.
    """
    def __init__(self):
        self.mode = "tasks"
        self.detector = None
        self.drawing_utils = None
        self.connections = None
        self._frame_ts_ms = 0

        # Cek apakah legacy solutions API tersedia
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "hands"):
            self.mode = "legacy"
            self.mp_hands = mp.solutions.hands
            self.drawing_utils = mp.solutions.drawing_utils
            self.connections = self.mp_hands.HAND_CONNECTIONS
            self.detector = self.mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=2,
                model_complexity=1,
                min_detection_confidence=0.7,
                min_tracking_confidence=0.7,
            )
            return

        # Modern Tasks API — VIDEO mode untuk temporal tracking
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        tools_dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.join(tools_dir, "hand_landmarker.task")
        if not os.path.exists(model_path):
            print("[INFO] Mengunduh model hand_landmarker.task...")
            url = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
            urllib.request.urlretrieve(url, model_path)

        base_options = mp_python.BaseOptions(model_asset_path=model_path)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.7,
            min_tracking_confidence=0.7,
        )
        self.detector = vision.HandLandmarker.create_from_options(options)
        self.drawing_utils = vision.drawing_utils
        self.connections = vision.HandLandmarksConnections.HAND_CONNECTIONS

    def detect(self, rgb_frame: np.ndarray) -> list:
        """
        Mengembalikan list of tuple: [(landmarks_21, handedness_label), ...]
        di mana handedness_label bernilai 'Right', 'Left', atau 'Unknown'.
        """
        if self.mode == "legacy":
            res = self.detector.process(rgb_frame)
            if not res.multi_hand_landmarks:
                return []
            hands = []
            for i, hand_lm in enumerate(res.multi_hand_landmarks):
                label = "Unknown"
                if hasattr(res, "multi_handedness") and res.multi_handedness and i < len(res.multi_handedness):
                    label = res.multi_handedness[i].classification[0].label
                hands.append((hand_lm.landmark, label))
            return hands
        else:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            curr_ts = int(time.perf_counter() * 1000)
            self._frame_ts_ms = max(self._frame_ts_ms + 1, curr_ts)
            res = self.detector.detect_for_video(mp_image, self._frame_ts_ms)
            if not res.hand_landmarks:
                return []
            hands = []
            for i, lm in enumerate(res.hand_landmarks):
                label = "Unknown"
                if res.handedness and i < len(res.handedness) and len(res.handedness[i]) > 0:
                    label = res.handedness[i][0].category_name or res.handedness[i][0].display_name or "Unknown"
                hands.append((lm, label))
            return hands

    def draw_landmarks(self, frame: np.ndarray, landmarks_list) -> None:
        if self.drawing_utils and self.connections:
            self.drawing_utils.draw_landmarks(frame, landmarks_list, self.connections)


class PortalProcessor:
    GEOMETRY_MODES = [
        "2D-Quad",
        "3D-Prism-Cube",
        "Magic-Mandala",
        "Plasma-Laser",
        "3D-Dual-Ribbon"
    ]

    def __init__(self, cfg: PipelineConfig):
        self.cfg = cfg
        self.filters: Dict[str, Callable[[np.ndarray], np.ndarray]] = {
            "anime-style": FilterBank.anime_style,
            "cyberpunk-neon": FilterBank.cyberpunk_neon,
            "matrix-code": FilterBank.matrix_code,
            "vaporwave-80s": FilterBank.vaporwave_80s,
            "hologram": FilterBank.hologram,
            "tv-static-nosignal": FilterBank.tv_static_nosignal,
            "vintage-1920-film": FilterBank.vintage_1920_film,
            "kaleidoscope-mirror": FilterBank.kaleidoscope_mirror,
            "psychedelic-aura": FilterBank.psychedelic_aura,
            "laser-wireframe": FilterBank.laser_wireframe,
            "fire-plasma": FilterBank.fire_plasma,
            "night-vision": FilterBank.night_vision,
            "comic-pop-art": FilterBank.comic_pop_art,
            "dual-tone": FilterBank.dual_tone,
            "thermal": FilterBank.thermal,
            "sketch": FilterBank.sketch,
            "pixelate": FilterBank.pixelate,
            "glitch": FilterBank.glitch,
            "invert": FilterBank.invert,
            "red-channel": FilterBank.red_channel,
            "edge": FilterBank.edge,
            "blur": FilterBank.blur,
            "cartoon": FilterBank.cartoon,
            "rainbow-wave": FilterBank.rainbow_wave,
        }
        self.filter_keys = list(self.filters.keys())
        self.active_filter_idx = 0
        
        # 3D / Geometry Mode selection (Berubah via tombol 'C')
        self.active_geom_idx = 0
        
        self.last_switch_time = 0.0
        self.last_screenshot_time = 0.0
        self.last_mode_toggle = 0.0

        # Gestur Ganti Filter (Tangan Kanan: Jempol + Kelingking)
        self._filter_pinch_hold_count = 0
        self._filter_pinch_fired = False

        # Gestur Screenshot Layar (Tangan Kiri: Jempol + Kelingking)
        self._screenshot_hold_count = 0
        self._screenshot_fired = False

        # Gestur Snap/Jepret ke Arah Layar -> Blur Effect
        self._snap_prev_thumb_mid_dist: Dict[int, float] = {}
        self._snap_gun_pose_count: Dict[int, int] = {}
        self._snap_pinch_contact: Dict[int, float] = {}
        self._snap_cooldown_sec: float = 2.5
        self._snap_last_trigger: float = 0.0

        # High-Definition Blur Noises State (Cinematic Bokeh Defocus + 35mm Organic Film Grain)
        self._snap_blur_active: bool = False
        self._snap_blur_start_time: float = 0.0
        self._snap_blur_duration: float = 3.0  # Durasi blur dalam detik
        
        # Pre-generated 16 fine silver-halide organic film grain textures (pos/neg pairs) for HD Blur Noises
        self._grain_pairs: List[Tuple[np.ndarray, np.ndarray]] = []
        for _ in range(16):
            raw_noise = np.random.normal(0, 22.0, (self.cfg.frame_height, self.cfg.frame_width, 3))
            pos = np.clip(raw_noise, 0, 255).astype(np.uint8)
            neg = np.clip(-raw_noise, 0, 255).astype(np.uint8)
            self._grain_pairs.append((pos, neg))

        # Shutter flash animation & Toast notification
        self.flash_intensity = 0.0
        self.toast_message = ""
        self.toast_expire_time = 0.0

        # Velocity-aware adaptive landmark smoothing
        self._smooth_landmarks: Dict[int, List[Tuple[float, float]]] = {}

        self.hand_detector = HandDetector()

    @property
    def current_filter_name(self) -> str:
        return self.filter_keys[self.active_filter_idx]

    @property
    def secondary_filter_name(self) -> str:
        return self.filter_keys[(self.active_filter_idx + 1) % len(self.filter_keys)]

    @property
    def current_geom_mode_name(self) -> str:
        return self.GEOMETRY_MODES[self.active_geom_idx]

    def cycle_filter(self, step: int = 1) -> None:
        self.active_filter_idx = (self.active_filter_idx + step) % len(self.filter_keys)

    def cycle_geometry_mode(self, step: int = 1) -> None:
        self.active_geom_idx = (self.active_geom_idx + step) % len(self.GEOMETRY_MODES)

    def _smooth_hand(self, hand_idx: int, landmarks, w: int, h: int) -> List[Tuple[int, int]]:
        """
        Velocity-Aware Adaptive Smoothing:
        Meredam tremor/jitter tangan secara total saat diam,
        namun tetap responsif tanpa lag saat bergerak cepat.
        """
        raw = [(lm.x * w, lm.y * h) for lm in landmarks]

        if hand_idx not in self._smooth_landmarks or len(self._smooth_landmarks[hand_idx]) != 21:
            self._smooth_landmarks[hand_idx] = [(float(x), float(y)) for x, y in raw]
            return [(int(x), int(y)) for x, y in raw]

        prev = self._smooth_landmarks[hand_idx]
        smoothed = []
        for (rx, ry), (px, py) in zip(raw, prev):
            dist = np.hypot(rx - px, ry - py)
            alpha = float(np.clip(0.35 + (dist / 35.0) * 0.5, 0.35, 0.88))
            sx = alpha * rx + (1.0 - alpha) * px
            sy = alpha * ry + (1.0 - alpha) * py
            smoothed.append((sx, sy))

        self._smooth_landmarks[hand_idx] = smoothed
        return [(int(x), int(y)) for x, y in smoothed]

    def trigger_desktop_screenshot(self, current_frame: np.ndarray) -> None:
        """
        Mengambil screenshot seluruh layar desktop dan snapshot kamera aktif,
        memicu flash shutter animasi dan suara kamera.
        """
        self.flash_intensity = 1.0
        ScreenCaptureHelper.play_shutter_sound()

        tools_dir = os.path.dirname(os.path.abspath(__file__))
        screenshots_dir = os.path.join(tools_dir, "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)

        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        desktop_filename = f"desktop_{timestamp_str}.png"
        desktop_path = os.path.join(screenshots_dir, desktop_filename)

        desktop_img = ScreenCaptureHelper.capture_desktop()
        if desktop_img is not None:
            cv2.imwrite(desktop_path, desktop_img)
            self.toast_message = f"SCREENSHOT DISIMPAN: {desktop_filename}"
        else:
            cam_path = os.path.join(screenshots_dir, f"capture_{timestamp_str}.png")
            cv2.imwrite(cam_path, current_frame)
            self.toast_message = f"FRAME DISIMPAN: capture_{timestamp_str}.png"

        self.toast_expire_time = time.time() + 3.0

    def trigger_blur(self) -> None:
        """Memicu efek blur kamera murni selama durasi yang ditentukan."""
        self._snap_blur_active = True
        self._snap_blur_start_time = time.time()
        self._snap_last_trigger = time.time()

    def stop_blur(self) -> None:
        """Mematikan / menonaktifkan efek blur kamera seketika."""
        self._snap_blur_active = False
        self._snap_blur_start_time = 0.0

    def toggle_blur(self) -> None:
        """Toggle aktif/nonaktif efek blur kamera."""
        if self._snap_blur_active:
            self.stop_blur()
        else:
            self.trigger_blur()

    def render_portal_polygon(self, frame: np.ndarray, pts: List[Tuple[int, int]], filter_key: str, border_color=(255, 255, 255), thickness=2) -> np.ndarray:
        poly = np.array(pts, dtype=np.int32)
        x, y, w, h = cv2.boundingRect(poly)
        x, y = max(0, x), max(0, y)
        w, h = min(w, frame.shape[1] - x), min(h, frame.shape[0] - y)

        if w <= 10 or h <= 10:
            return frame

        roi = frame[y : y + h, x : x + w].copy()
        processed_roi = self.filters[filter_key](roi)

        mask = np.zeros((h, w), dtype=np.uint8)
        cv2.fillPoly(mask, [poly - [x, y]], 255)
        mask_3c = cv2.merge([mask, mask, mask])

        bg = cv2.bitwise_and(roi, cv2.bitwise_not(mask_3c))
        fg = cv2.bitwise_and(processed_roi, mask_3c)
        frame[y : y + h, x : x + w] = cv2.add(bg, fg)

        if thickness > 0:
            cv2.polylines(frame, [poly], isClosed=True, color=border_color, thickness=thickness)
        return frame

    def render_3d_prism_cube(self, frame: np.ndarray, p1: Tuple[int, int], p2: Tuple[int, int], filter_key: str) -> np.ndarray:
        """Merender prisma/kubus 3D wireframe dengan efek perspektif dan kedalaman spasial."""
        x1, y1 = p1
        x2, y2 = p2
        dx = x2 - x1
        dy = y2 - y1
        dist = math.hypot(dx, dy)
        if dist < 25:
            return frame

        nx = -dy / dist * (dist * 0.42)
        ny = dx / dist * (dist * 0.42)

        # 4 Titik Wajah Depan
        f0 = (int(x1 - nx), int(y1 - ny))
        f1 = (int(x2 - nx), int(y2 - ny))
        f2 = (int(x2 + nx), int(y2 + ny))
        f3 = (int(x1 + nx), int(y1 + ny))

        # 4 Titik Wajah Belakang (Depth Perspective Offset)
        z_off_x = int(nx * 0.45 + 20)
        z_off_y = int(ny * 0.45 - 28)
        b0 = (f0[0] + z_off_x, f0[1] + z_off_y)
        b1 = (f1[0] + z_off_x, f1[1] + z_off_y)
        b2 = (f2[0] + z_off_x, f2[1] + z_off_y)
        b3 = (f3[0] + z_off_x, f3[1] + z_off_y)

        # Render filter di wajah depan
        frame = self.render_portal_polygon(frame, [f0, f1, f2, f3], filter_key, border_color=(0, 255, 255), thickness=2)

        # Gambar garis kerangka kubus 3D (Wireframe Depth Pillars)
        back_poly = np.array([b0, b1, b2, b3], dtype=np.int32)
        cv2.polylines(frame, [back_poly], isClosed=True, color=(255, 140, 0), thickness=1)

        for v_f, v_b in zip([f0, f1, f2, f3], [b0, b1, b2, b3]):
            cv2.line(frame, v_f, v_b, (0, 220, 255), 2)

        # Glow vertex corners
        for v in [f0, f1, f2, f3, b0, b1, b2, b3]:
            cv2.circle(frame, v, 5, (0, 255, 255), -1)

        return frame

    def render_doctor_strange_mandala(self, frame: np.ndarray, center: Tuple[int, int], radius: float, filter_key: str, t: float) -> np.ndarray:
        """Merender perisai sihir Doctor Strange dengan mandala putar dan partikel energi."""
        cx, cy = int(center[0]), int(center[1])
        r = max(25, int(radius))

        # Filter di lingkaran inti portal
        pts_circle = []
        for i in range(24):
            ang = i * 2.0 * math.pi / 24.0
            px = int(cx + r * 0.75 * math.cos(ang))
            py = int(cy + r * 0.75 * math.sin(ang))
            pts_circle.append((px, py))

        frame = self.render_portal_polygon(frame, pts_circle, filter_key, border_color=(0, 200, 255), thickness=2)

        # Cincin luar & dalam geometris
        cv2.circle(frame, (cx, cy), r, (0, 165, 255), 2)
        cv2.circle(frame, (cx, cy), int(r * 0.88), (0, 220, 255), 1)
        cv2.circle(frame, (cx, cy), int(r * 0.40), (0, 255, 240), 2)

        # Bintang 8 sudut berputar searah jarum jam
        pts8 = []
        for i in range(8):
            ang = (i * math.pi / 4.0) + (t * 1.6)
            px = int(cx + r * 0.88 * math.cos(ang))
            py = int(cy + r * 0.88 * math.sin(ang))
            pts8.append((px, py))
        cv2.polylines(frame, [np.array(pts8, dtype=np.int32)], isClosed=True, color=(0, 220, 255), thickness=1)

        # Kotak rune dalam berputar berlawanan jarum jam
        sq = []
        for i in range(4):
            ang = (i * math.pi / 2.0) - (t * 2.2)
            px = int(cx + r * 0.60 * math.cos(ang))
            py = int(cy + r * 0.60 * math.sin(ang))
            sq.append((px, py))
        cv2.polylines(frame, [np.array(sq, dtype=np.int32)], isClosed=True, color=(0, 200, 255), thickness=2)

        # Percikan partikel sihir mengorbit
        for k in range(8):
            spark_ang = (k * math.pi / 4.0) + (t * 3.8)
            dist_p = r * (0.96 + 0.16 * math.sin(t * 6.0 + k))
            sx = int(cx + dist_p * math.cos(spark_ang))
            sy = int(cy + dist_p * math.sin(spark_ang))
            cv2.circle(frame, (sx, sy), 3, (160, 240, 255), -1)

        return frame

    def render_plasma_laser_bridge(self, frame: np.ndarray, p1: Tuple[int, int], p2: Tuple[int, int], filter_key: str, t: float) -> np.ndarray:
        """Merender jembatan laser plasma dan busur petir antar tangan."""
        x1, y1 = p1
        x2, y2 = p2
        dx = x2 - x1
        dy = y2 - y1
        dist = math.hypot(dx, dy)
        if dist < 20:
            return frame

        # Portal filter pita di tengah laser
        nx = -dy / dist * 35.0
        ny = dx / dist * 35.0
        poly = [(int(x1 - nx), int(y1 - ny)), (int(x2 - nx), int(y2 - ny)),
                (int(x2 + nx), int(y2 + ny)), (int(x1 + nx), int(y1 + ny))]
        frame = self.render_portal_polygon(frame, poly, filter_key, border_color=(255, 120, 0), thickness=1)

        # Sinar laser ganda bercahaya
        cv2.line(frame, (int(x1), int(y1)), (int(x2), int(y2)), (255, 140, 0), 6)
        cv2.line(frame, (int(x1), int(y1)), (int(x2), int(y2)), (255, 255, 255), 2)

        # Busur petir dinamis (Jagged Electric Arc)
        segments = 12
        arc_pts = [(int(x1), int(y1))]
        for i in range(1, segments):
            frac = i / segments
            bx = x1 + dx * frac
            by = y1 + dy * frac
            perp_x = -dy / dist * random.uniform(-16, 16)
            perp_y = dx / dist * random.uniform(-16, 16)
            arc_pts.append((int(bx + perp_x), int(by + perp_y)))
        arc_pts.append((int(x2), int(y2)))
        cv2.polylines(frame, [np.array(arc_pts, dtype=np.int32)], isClosed=False, color=(255, 230, 80), thickness=2)

        # Cincin energi berdenyut sepanjang laser
        for r_idx in range(4):
            phase = (t * 2.5 + r_idx * 0.25) % 1.0
            rx = int(x1 + dx * phase)
            ry = int(y1 + dy * phase)
            ring_r = int(12 + math.sin(t * 10.0 + r_idx) * 4)
            cv2.circle(frame, (rx, ry), ring_r, (0, 240, 255), 2)

        # Bola energi anchor di kedua ujung tangan
        cv2.circle(frame, (int(x1), int(y1)), 14, (0, 200, 255), -1)
        cv2.circle(frame, (int(x1), int(y1)), 7, (255, 255, 255), -1)
        cv2.circle(frame, (int(x2), int(y2)), 14, (0, 200, 255), -1)
        cv2.circle(frame, (int(x2), int(y2)), 7, (255, 255, 255), -1)

        return frame

    def process_frame(self, raw_frame: np.ndarray) -> np.ndarray:
        frame = cv2.flip(raw_frame, 1)
        
        # Perbaiki aspek rasio: center-crop ke rasio target tanpa membuat gambar melebar
        h_in, w_in = frame.shape[:2]
        target_ar = self.cfg.frame_width / self.cfg.frame_height
        cur_ar = w_in / h_in

        if cur_ar < target_ar - 0.02:
            desired_h = int(w_in / target_ar)
            offset_y = max(0, (h_in - desired_h) // 2)
            frame = frame[offset_y : offset_y + desired_h, :]
        elif cur_ar > target_ar + 0.02:
            desired_w = int(h_in * target_ar)
            offset_x = max(0, (w_in - desired_w) // 2)
            frame = frame[:, offset_x : offset_x + desired_w]

        frame = cv2.resize(frame, (self.cfg.frame_width, self.cfg.frame_height), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        
        hand_data = self.hand_detector.detect(rgb)
        now = time.time()
        
        all_hand_tips = []
        all_hand_centers = []
        all_hand_scales = []
        is_bowtie = False
        right_filter_pinch_active = False
        screenshot_gesture_active = False
        snap_gesture_detected = False

        # Bersihkan smooth data untuk tangan yang sudah hilang
        active_indices = set(range(len(hand_data)))
        for idx in list(self._smooth_landmarks.keys()):
            if idx not in active_indices:
                del self._smooth_landmarks[idx]

        if hand_data:
            for hand_idx, (hand_lm, hand_label) in enumerate(hand_data):
                self.hand_detector.draw_landmarks(frame, hand_lm)

                # Smooth landmarks
                smoothed = self._smooth_hand(hand_idx, hand_lm, self.cfg.frame_width, self.cfg.frame_height)
                # Landmark index: 0(Wrist), 4(Thumb), 8(Index), 12(Middle), 16(Ring), 20(Pinky)
                tips = [smoothed[i] for i in [4, 8, 12, 16, 20]]
                all_hand_tips.append(tips)

                wrist_pt = smoothed[0]
                middle_mcp_pt = smoothed[9]
                palm_center = (int((wrist_pt[0] + middle_mcp_pt[0]) / 2), int((wrist_pt[1] + middle_mcp_pt[1]) / 2))
                all_hand_centers.append(palm_center)

                # Skala ukuran tangan
                hand_scale = float(np.hypot(wrist_pt[0] - middle_mcp_pt[0], wrist_pt[1] - middle_mcp_pt[1]))
                all_hand_scales.append(hand_scale)

                dynamic_pinch_thresh = float(np.clip(hand_scale * 0.35, 30.0, 68.0))

                thumb_pt = tips[0]        # Ujung Jempol (4)
                pinky_pt = tips[4]        # Ujung Kelingking (20)
                pinky_dip = smoothed[19]  # Sendi bawah kelingking

                # Cek tangan spesifik:
                # TANGAN KANAN -> Jempol + Kelingking = GANTI FILTER
                # TANGAN KIRI  -> Jempol + Kelingking = SCREENSHOT LAYAR
                is_right_hand = (hand_label.lower() == "right")
                is_left_hand = (hand_label.lower() == "left")

                # Fallback jika hanya 1 tangan terdeteksi dan label MediaPipe
                if len(hand_data) == 1:
                    if hand_label.lower() != "left":
                        is_right_hand = True
                    if hand_label.lower() != "right":
                        is_left_hand = True

                dist_thumb_pinky = min(
                    GeometryUtils.euclidean_dist(thumb_pt, pinky_pt),
                    GeometryUtils.euclidean_dist(thumb_pt, pinky_dip)
                )

                # =========================================================
                # Gestur 1 (TANGAN KANAN): Jempol (4) bertemu Kelingking (20) -> GANTI FILTER
                # =========================================================
                if is_right_hand:
                    if dist_thumb_pinky < dynamic_pinch_thresh:
                        right_filter_pinch_active = True
                        cv2.line(frame, thumb_pt, pinky_pt, (0, 255, 0), 4)
                        cv2.circle(frame, thumb_pt, 9, (0, 255, 0), -1)
                        cv2.circle(frame, pinky_pt, 9, (0, 255, 0), -1)
                    elif dist_thumb_pinky < dynamic_pinch_thresh * 1.45:
                        cv2.line(frame, thumb_pt, pinky_pt, (0, 255, 255), 1)
                        cv2.circle(frame, thumb_pt, 4, (0, 255, 255), -1)
                        cv2.circle(frame, pinky_pt, 4, (0, 255, 255), -1)

                # =========================================================
                # Gestur 2 (TANGAN KIRI): Jempol (4) bertemu Kelingking (20) -> SCREENSHOT LAYAR
                # =========================================================
                if is_left_hand:
                    if dist_thumb_pinky < dynamic_pinch_thresh:
                        screenshot_gesture_active = True
                        mid_touch_pt = (int((thumb_pt[0] + pinky_pt[0]) / 2), int((thumb_pt[1] + pinky_pt[1]) / 2))
                        cv2.line(frame, thumb_pt, pinky_pt, (255, 60, 255), 4)
                        cv2.circle(frame, thumb_pt, 10, (255, 60, 255), -1)
                        cv2.circle(frame, pinky_pt, 10, (255, 60, 255), -1)
                        cv2.circle(frame, mid_touch_pt, int(18 + math.sin(now * 15.0) * 4), (0, 255, 255), 2)
                    elif dist_thumb_pinky < dynamic_pinch_thresh * 1.45:
                        cv2.line(frame, thumb_pt, pinky_pt, (200, 120, 255), 1)
                        cv2.circle(frame, thumb_pt, 5, (200, 120, 255), -1)
                        cv2.circle(frame, pinky_pt, 5, (200, 120, 255), -1)

                # =========================================================
                # Gestur 3 (TANGAN KIRI SAJA): Gerakan Menembak (Finger Gun Snap) -> BLUR NOISES
                # Hanya terdeteksi jika dilakukan oleh Tangan Kiri
                # =========================================================
                if is_left_hand:
                    index_tip = smoothed[8]
                    index_pip = smoothed[6]
                    middle_tip = smoothed[12]
                    middle_pip = smoothed[10]
                    ring_tip = smoothed[16]
                    ring_pip = smoothed[14]
                    pinky_tip = smoothed[20]
                    pinky_pip = smoothed[17]
                    wrist = smoothed[0]

                    # Cek pose Finger Gun: Telunjuk lurus mengarah ke depan, jari lainnya tertekuk
                    index_dist = GeometryUtils.euclidean_dist(index_tip, wrist)
                    index_pip_dist = GeometryUtils.euclidean_dist(index_pip, wrist)
                    middle_dist = GeometryUtils.euclidean_dist(middle_tip, wrist)
                    middle_pip_dist = GeometryUtils.euclidean_dist(middle_pip, wrist)
                    ring_dist = GeometryUtils.euclidean_dist(ring_tip, wrist)
                    ring_pip_dist = GeometryUtils.euclidean_dist(ring_pip, wrist)

                    index_extended = index_dist > index_pip_dist * 1.15
                    middle_curled = middle_dist < middle_pip_dist * 1.30
                    ring_curled = ring_dist < ring_pip_dist * 1.30

                    is_gun_pose = index_extended and middle_curled and ring_curled

                    thumb_to_middle = GeometryUtils.euclidean_dist(thumb_pt, middle_tip)
                    thumb_to_index = GeometryUtils.euclidean_dist(thumb_pt, index_tip)

                    prev_dist_mid = self._snap_prev_thumb_mid_dist.get(hand_idx, thumb_to_middle)
                    self._snap_prev_thumb_mid_dist[hand_idx] = thumb_to_middle

                    if is_gun_pose:
                        self._snap_gun_pose_count[hand_idx] = self._snap_gun_pose_count.get(hand_idx, 0) + 1
                        gun_frames = self._snap_gun_pose_count.get(hand_idx, 0)
                        snap_delta = prev_dist_mid - thumb_to_middle

                        # Visual Laser Aiming Crosshair di ujung telunjuk tangan kiri saat pose menembak
                        cv2.circle(frame, index_tip, 12, (0, 255, 255), 2)
                        cv2.circle(frame, index_tip, 4, (0, 200, 255), -1)
                        cv2.line(frame, (index_tip[0] - 18, index_tip[1]), (index_tip[0] + 18, index_tip[1]), (0, 255, 255), 1)
                        cv2.line(frame, (index_tip[0], index_tip[1] - 18), (index_tip[0], index_tip[1] + 18), (0, 255, 255), 1)
                        cv2.putText(frame, "READY TO SHOOT", (index_tip[0] + 18, index_tip[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)

                        if (snap_delta > hand_scale * 0.08
                                and thumb_to_middle < hand_scale * 0.50
                                and gun_frames >= 2
                                and now - self._snap_last_trigger > self._snap_cooldown_sec):
                            snap_gesture_detected = True
                    else:
                        self._snap_gun_pose_count[hand_idx] = 0

                        # Deteksi Alternatif: Quick Pinch-Snap Jentik Jari Tangan Kiri
                        if thumb_to_index < dynamic_pinch_thresh * 0.9 or thumb_to_middle < dynamic_pinch_thresh * 0.9:
                            self._snap_pinch_contact[hand_idx] = now
                        elif hand_idx in self._snap_pinch_contact:
                            contact_time = self._snap_pinch_contact.pop(hand_idx)
                            if (0.03 < now - contact_time < 0.30
                                    and (thumb_to_index > dynamic_pinch_thresh * 1.25 or thumb_to_middle > dynamic_pinch_thresh * 1.25)
                                    and now - self._snap_last_trigger > self._snap_cooldown_sec):
                                snap_gesture_detected = True

        # Logic Trigger Ganti Filter (Tangan Kanan)
        if right_filter_pinch_active:
            self._filter_pinch_hold_count += 1
        else:
            self._filter_pinch_hold_count = 0
            self._filter_pinch_fired = False

        if (self._filter_pinch_hold_count >= self.cfg.pinch_hold_frames
                and not self._filter_pinch_fired
                and now - self.last_switch_time > self.cfg.filter_cooldown_sec):
            self.cycle_filter(1)
            self.last_switch_time = now
            self._filter_pinch_fired = True

        # Logic Trigger Screenshot Layar (Tangan Kiri)
        if screenshot_gesture_active:
            self._screenshot_hold_count += 1
        else:
            self._screenshot_hold_count = 0
            self._screenshot_fired = False

        if (self._screenshot_hold_count >= self.cfg.screenshot_hold_frames
                and not self._screenshot_fired
                and now - self.last_screenshot_time > self.cfg.screenshot_cooldown_sec):
            self.trigger_desktop_screenshot(frame.copy())
            self.last_screenshot_time = now
            self._screenshot_fired = True

        # Logic Trigger Snap Blur
        if snap_gesture_detected:
            self.trigger_blur()

        # =========================================================
        # Render Geometri Berdasarkan Mode Terpilih (Tombol 'C')
        # =========================================================
        geom_mode = self.current_geom_mode_name

        if hand_data:
            if geom_mode == "2D-Quad":
                if len(all_hand_tips) == 2:
                    corners = [all_hand_tips[0][0], all_hand_tips[0][1], all_hand_tips[1][0], all_hand_tips[1][1]]
                    if GeometryUtils.is_hand_rotated(corners[0], corners[1]) or GeometryUtils.is_hand_rotated(corners[2], corners[3]):
                        quad = GeometryUtils.sort_quad_bowtie(corners)
                        is_bowtie = True
                    else:
                        quad = GeometryUtils.sort_quad_clean(corners)
                    frame = self.render_portal_polygon(frame, quad, self.current_filter_name)
                elif len(all_hand_tips) == 1:
                    t = all_hand_tips[0]
                    frame = self.render_portal_polygon(frame, [t[0], t[1], t[2], t[4]], self.current_filter_name)

            elif geom_mode == "3D-Prism-Cube":
                if len(all_hand_tips) == 2:
                    p1 = (int((all_hand_tips[0][0][0] + all_hand_tips[0][1][0]) / 2), int((all_hand_tips[0][0][1] + all_hand_tips[0][1][1]) / 2))
                    p2 = (int((all_hand_tips[1][0][0] + all_hand_tips[1][0][1]) / 2), int((all_hand_tips[1][0][1] + all_hand_tips[1][0][1]) / 2))
                    frame = self.render_3d_prism_cube(frame, p1, p2, self.current_filter_name)
                elif len(all_hand_tips) == 1:
                    t = all_hand_tips[0]
                    frame = self.render_3d_prism_cube(frame, t[0], t[4], self.current_filter_name)

            elif geom_mode == "Magic-Mandala":
                for i, center in enumerate(all_hand_centers):
                    r = all_hand_scales[i] * 0.95 if i < len(all_hand_scales) else 90.0
                    frame = self.render_doctor_strange_mandala(frame, center, r, self.current_filter_name, now)

            elif geom_mode == "Plasma-Laser":
                if len(all_hand_tips) == 2:
                    p1 = all_hand_tips[0][1]
                    p2 = all_hand_tips[1][1]
                    frame = self.render_plasma_laser_bridge(frame, p1, p2, self.current_filter_name, now)
                elif len(all_hand_tips) == 1:
                    t = all_hand_tips[0]
                    frame = self.render_plasma_laser_bridge(frame, t[0], t[4], self.current_filter_name, now)

            elif geom_mode == "3D-Dual-Ribbon":
                if len(all_hand_tips) == 2:
                    t1, t2 = all_hand_tips[0], all_hand_tips[1]
                    frame = self.render_portal_polygon(frame, [t1[0], t1[1], t1[2], t2[2], t2[1], t2[0]], self.current_filter_name, border_color=(0, 255, 255))
                    frame = self.render_portal_polygon(frame, [t1[2], t1[3], t1[4], t2[4], t2[3], t2[2]], self.secondary_filter_name, border_color=(255, 0, 255))
                elif len(all_hand_tips) == 1:
                    frame = self.render_portal_polygon(frame, all_hand_tips[0], self.current_filter_name)

        # =========================================================
        # Snap Blur Effect — High-Definition Cinematic Bokeh Defocus & Organic Film Noise
        # =========================================================
        if self._snap_blur_active:
            elapsed = now - self._snap_blur_start_time
            if elapsed < self._snap_blur_duration:
                progress = elapsed / self._snap_blur_duration
                # Blur tetap pekat di 65% durasi awal, lalu meluruh halus kembali normal
                blur_factor = 1.0 if progress < 0.65 else (1.0 - (progress - 0.65) / 0.35)

                if blur_factor > 0.02:
                    h_f, w_f = frame.shape[:2]
                    
                    # 1. Multi-Scale Optical Bokeh Defocus
                    ds_factor = 1.0 + blur_factor * 14.0
                    ds_w = max(16, int(w_f / ds_factor))
                    ds_h = max(16, int(h_f / ds_factor))

                    small = cv2.resize(frame, (ds_w, ds_h), interpolation=cv2.INTER_LINEAR)
                    k = max(3, int(blur_factor * 29)) | 1
                    small_blurred = cv2.GaussianBlur(small, (k, k), 0)
                    base_blur = cv2.resize(small_blurred, (w_f, h_f), interpolation=cv2.INTER_LINEAR)

                    # 2. Chromatic Dispersion Bokeh (Anamorphic Lens Out-of-Focus Aberration)
                    shift = int(round(blur_factor * 3.5))
                    if shift > 0:
                        b_ch, g_ch, r_ch = cv2.split(base_blur)
                        r_shifted = np.roll(r_ch, shift, axis=1)
                        b_shifted = np.roll(b_ch, -shift, axis=1)
                        base_blur = cv2.merge([b_shifted, g_ch, r_shifted])

                    # 3. High-Definition 35mm Silver-Halide Organic Film Grain Noise
                    if self._grain_pairs:
                        g_idx = int((now * 42) % len(self._grain_pairs))
                        pos_g, neg_g = self._grain_pairs[g_idx]

                        scaled_pos = cv2.convertScaleAbs(pos_g, alpha=blur_factor)
                        scaled_neg = cv2.convertScaleAbs(neg_g, alpha=blur_factor)

                        noisy_blur = cv2.add(base_blur, scaled_pos)
                        noisy_blur = cv2.subtract(noisy_blur, scaled_neg)
                    else:
                        noisy_blur = base_blur

                    frame = cv2.addWeighted(noisy_blur, blur_factor, frame, 1.0 - blur_factor, 0)
            else:
                self._snap_blur_active = False

        # Shutter Flash Animation
        if self.flash_intensity > 0.01:
            white_flash = np.full_like(frame, 255)
            frame = cv2.addWeighted(white_flash, self.flash_intensity, frame, 1.0 - self.flash_intensity, 0)
            self.flash_intensity = max(0.0, self.flash_intensity - 0.15)

        self._draw_hud(frame, is_bowtie, right_filter_pinch_active, screenshot_gesture_active, snap_gesture_detected, now)
        return frame

    def _draw_hud(self, frame: np.ndarray, is_bowtie: bool, right_pinch: bool, screenshot_gesture: bool, snap_detected: bool, now: float) -> None:
        geom_name = self.current_geom_mode_name
        cv2.putText(frame, f"3D SHAPE: {geom_name.upper()} [Tekan 'C' untuk ganti bentuk]", (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        cv2.putText(frame, f"FILTER: {self.current_filter_name.upper()} [Kanan: Jempol+Kelingking]", (15, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 2)
        cv2.putText(frame, "SCREENSHOT: [KIRI: Jempol+Kelingking / 'S']", (15, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (200, 200, 200), 2)
        cv2.putText(frame, "BLUR NOISES: [KIRI: Tembak / 'B' Toggle / 'X' Matikan]", (15, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (0, 200, 255), 2)

        if right_pinch:
            cv2.putText(frame, ">> GESTUR TERDETEKSI: GANTI FILTER (KANAN) <<", (15, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)
        elif screenshot_gesture:
            cv2.putText(frame, ">> GESTUR SCREENSHOT: MENGAMBIL FOTO LAYAR (KIRI) <<", (15, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 60, 255), 2)
        elif self._snap_blur_active:
            remaining = max(0.0, self._snap_blur_duration - (now - self._snap_blur_start_time))
            cv2.putText(frame, f">> BLUR NOISES AKTIF: {remaining:.1f}s <<", (15, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)

        # Toast Notification Banner saat screenshot berhasil diambil
        if now < self.toast_expire_time and self.toast_message:
            tw, th = 620, 42
            tx, ty = (self.cfg.frame_width - tw) // 2, self.cfg.frame_height - 60
            overlay = frame.copy()
            cv2.rectangle(overlay, (tx, ty), (tx + tw, ty + th), (20, 20, 20), -1)
            cv2.rectangle(overlay, (tx, ty), (tx + tw, ty + th), (0, 255, 0), 2)
            frame[:] = cv2.addWeighted(overlay, 0.88, frame, 0.12, 0)
            cv2.putText(frame, self.toast_message, (tx + 18, ty + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (0, 255, 0), 2)


def open_active_camera(preferred_idx: int = 1) -> Tuple[cv2.VideoCapture, int]:
    """
    Mencari dan membuka kamera RGB aktif secara otomatis.
    Mencegah pemilihan sensor IR (Windows Hello) yang menghasilkan layar hitam.
    """
    indices_to_try = [preferred_idx] + [i for i in [0, 1, 2, 3] if i != preferred_idx]
    
    for test_idx in indices_to_try:
        for backend in [cv2.CAP_DSHOW, None]:
            try:
                cap = cv2.VideoCapture(test_idx) if backend is None else cv2.VideoCapture(test_idx, backend)
                if not cap.isOpened():
                    continue
                
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                cap.set(cv2.CAP_PROP_FPS, 30)
                
                has_signal = False
                for _ in range(8):
                    ret, f = cap.read()
                    if ret and f is not None and np.mean(f) > 0.05:
                        has_signal = True
                        break
                        
                if has_signal:
                    print(f"[INFO] Kamera aktif terdeteksi pada Index {test_idx} ({'DSHOW' if backend else 'DEFAULT'})")
                    return cap, test_idx
                
                cap.release()
            except Exception:
                pass

    print("[WARN] Membuka fallback kamera index 0")
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    return cap, 0


class KeyboardHandler:
    """
    Menangani input keyboard dengan dukungan ganda:
    1. OpenCV cv2.waitKey (case-insensitive + ESC + TAB)
    2. Windows Win32 GetAsyncKeyState (bekerja bahkan jika window OpenCV kehilangan fokus)
    Dengan debounce cerdas agar tidak berulang kali trigger saat tombol ditekan.
    """
    def __init__(self):
        self._key_down_prev: Dict[int, bool] = {}
        self._user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "user32") else None

    def check_pressed(self, vk_code: int, cv2_key: int, char_code: str) -> bool:
        # 1. Cek via OpenCV waitKey
        if cv2_key != 255 and cv2_key != -1:
            if char_code and len(char_code) == 1:
                if cv2_key == ord(char_code.lower()) or cv2_key == ord(char_code.upper()):
                    return True
            if char_code == "ESC" and cv2_key == 27:
                return True
            if char_code == "TAB" and cv2_key == 9:
                return True

        # 2. Cek via Win32 GetAsyncKeyState (Global hotkey dengan debounce)
        if self._user32:
            is_down = bool(self._user32.GetAsyncKeyState(vk_code) & 0x8000)
            was_down = self._key_down_prev.get(vk_code, False)
            self._key_down_prev[vk_code] = is_down
            if is_down and not was_down:
                return True

        return False


def main() -> None:
    cfg = PipelineConfig()
    processor = PortalProcessor(cfg)
    kb = KeyboardHandler()
    
    cap, current_cam_idx = open_active_camera(preferred_idx=1)

    if not cap.isOpened():
        print("[ERROR] Kamera tidak terdeteksi!")
        return

    print("\n=======================================================")
    print("           RETROLENS ENGINE - GESTURE CONTROL           ")
    print("=======================================================")
    print("  - Ganti Bentuk 3D  : Tekan 'C' (Quad, Prism, Mandala, Laser, Ribbon)")
    print("  - Ganti Filter     : TANGAN KANAN (Jempol + Kelingking) / 'N','P'")
    print("  - Screenshot Layar : TANGAN KIRI (Jempol + Kelingking) / 'S'")
    print("  - Blur Noises      : TANGAN KIRI (Gerakan Menembak) / 'B' (Toggle) / 'X' (Matikan)")
    print("  - Ganti Kamera     : Tekan 'TAB' (Kamera 0 <-> Kamera 1)")
    print("  - Keluar           : Tekan 'Q' atau 'ESC'")
    print("=======================================================\n")

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[ERROR] Gagal membaca frame kamera.")
            break

        out_frame = processor.process_frame(frame)
        cv2.imshow("RetroLens Engine", out_frame)

        cv2_key = cv2.waitKey(1) & 0xFF

        # Exit: 'Q' atau 'ESC'
        if kb.check_pressed(0x51, cv2_key, "Q") or kb.check_pressed(0x1B, cv2_key, "ESC"):
            print("[INFO] Menutup program...")
            break
        # Ganti Mode Bentuk 3D: 'C'
        elif kb.check_pressed(0x43, cv2_key, "C"):
            processor.cycle_geometry_mode(1)
            print(f"[INFO] Bentuk 3D aktif: {processor.current_geom_mode_name}")
        # Filter Berikutnya: 'N'
        elif kb.check_pressed(0x4E, cv2_key, "N"):
            processor.cycle_filter(1)
            print(f"[INFO] Filter aktif: {processor.current_filter_name}")
        # Filter Sebelumnya: 'P'
        elif kb.check_pressed(0x50, cv2_key, "P"):
            processor.cycle_filter(-1)
            print(f"[INFO] Filter aktif: {processor.current_filter_name}")
        # Screenshot Layar: 'S'
        elif kb.check_pressed(0x53, cv2_key, "S"):
            processor.trigger_desktop_screenshot(out_frame)
        # Blur Noises Toggle: 'B'
        elif kb.check_pressed(0x42, cv2_key, "B"):
            processor.toggle_blur()
        # Matikan Blur Noises Seketika: 'X'
        elif kb.check_pressed(0x58, cv2_key, "X"):
            processor.stop_blur()
        # Ganti Kamera: 'TAB'
        elif kb.check_pressed(0x09, cv2_key, "TAB"):
            next_idx = 0 if current_cam_idx == 1 else 1
            print(f"[INFO] Mencoba beralih ke Kamera Index {next_idx}...")
            test_cap, actual_idx = open_active_camera(preferred_idx=next_idx)
            if test_cap.isOpened():
                cap.release()
                cap = test_cap
                current_cam_idx = actual_idx

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
