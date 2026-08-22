# RetroLens Engine — AI Hand Gesture & 3D Spatial Geometry Filter Pipeline

> **Real-Time Computer Vision & Hand Landmark Tracking Engine** powered by **OpenCV** and **MediaPipe Tasks API**.

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![OpenCV](https://img.shields.io/badge/OpenCV-4.8%2B-green.svg)](https://opencv.org/)
[![MediaPipe](https://img.shields.io/badge/MediaPipe-0.10%2B-orange.svg)](https://developers.google.com/mediapipe)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📌 Overview

**RetroLens Engine** adalah aplikasi pengolahan citra video real-time berbasis pelacakan gestur tangan tanpa sentuh (*touchless hand gesture control*). Dilengkapi dengan **24 filter estetika visual** (mulai dari *Makoto Shinkai Anime Style*, *Sci-Fi Hologram dengan noise TV*, *Cyberpunk Neon*, hingga *1920s Vintage Film*) serta **5 mode geometri spasial 3D**.

Aplikasi ini juga dilengkapi modul **Windows GDI Desktop Screen Capture Engine** beresolusi asli (*DPI-Aware*) dengan animasi *camera shutter flash* dan *audio feedback* yang dapat dipicu secara instan hanya dengan gestur tangan kiri.

---

## ✨ Fitur Utama

1. **Dual-Hand Symmetric Gesture Control**:
   - **Tangan Kanan (Jempol ↔ Kelingking)**: Mengganti filter visual secara siklis (*Next Filter*).
   - **Tangan Kiri (Jempol ↔ Kelingking)**: Mengambil tangkapan layar penuh (*Full HD Desktop Screenshot*) dan menyimpannya secara otomatis.
2. **Velocity-Aware Adaptive Landmark Smoothing**:
   - Algoritma smoothing adaptif berbasis kecepatan: meredam tremor/jitter tangan saat diam (*alpha 0.35*) dan bebas lag saat tangan bergerak cepat (*alpha 0.88*).
3. **5 Mode Bentuk Spasial 3D & Portal (Ganti Cukup Tekan `C`)**:
   - **`2D-Quad`**: Portal quadrilateral 4 sudut adaptif dengan deteksi *bowtie auto-untangle*.
   - **`3D-Prism-Cube`**: Kubus wireframe 3D holografis dengan proyeksi kedalaman perspektif menghubungkan kedua tangan.
   - **`Magic-Mandala`**: Lingkaran sihir berputar Doctor Strange dengan bintang 8 sudut, rune geometris, dan partikel sihir mengorbit.
   - **`Plasma-Laser`**: Jembatan laser plasma ganda dan busur petir (*jagged electric arc*) di antara telunjuk kedua tangan.
   - **`3D-Dual-Ribbon`**: Pita polygonal segitiga 3D split-channel dengan warna ganda.
4. **24 Filter Visual Real-Time**:
   - `anime-style` (Makoto Shinkai / Kyoto Animation 2D Cel-Shading & Clean Line Art)
   - `cyberpunk-neon` (Electric cyan/magenta glow & dark backing)
   - `matrix-code` (Digital code rain scanlines)
   - `vaporwave-80s` (Synthwave sunset gradient & chromatic shift)
   - `hologram` (Sci-fi blue luminescence + dynamic TV static snow & tracking glitch)
   - `tv-static-nosignal` (Analog TV out-of-tune noise snow)
   - `vintage-1920-film` (Sepia silent movie with dust specks & vertical scratches)
   - `kaleidoscope-mirror` (4-quadrant radial optical symmetry)
   - `psychedelic-aura` (Solarized rainbow spectrum & hue cycling)
   - `laser-wireframe` (High-voltage cyan & gold wireframe contours)
   - Dan filter lainnya: `fire-plasma`, `night-vision`, `comic-pop-art`, `dual-tone`, `thermal`, `sketch`, `pixelate`, `glitch`, `invert`, `red-channel`, `edge`, `blur`, `cartoon`, `rainbow-wave`.
5. **Intelligent Aspect Ratio & Auto Camera Discovery**:
   - Otomatis mendeteksi kamera RGB aktif dan menghindari sensor IR (Windows Hello).
   - Memotong (*center-crop*) frame 4:3 menjadi proporsi natural 16:9 1280x720 HD tanpa distorsi melebar.

---

## 🎮 Kontrol Gestur & Keyboard

| Kontrol | Aksi | Deskripsi |
|---|---|---|
| **Gestur Tangan Kanan** | Jempol ↔ Kelingking | Ganti filter visual berikutnya |
| **Gestur Tangan Kiri** | Jempol ↔ Kelingking | Screenshot layar Desktop Full HD |
| **Gestur Tangan Kiri** | Gerakan Menembak (Finger Gun / Snap) | Picu efek kamera **Blur Noises** (3 detik) |
| **Tombol `C`** | Keyboard | Ganti Bentuk 3D *(Quad ➔ Prism ➔ Mandala ➔ Laser ➔ Ribbon)* |
| **Tombol `B`** | Keyboard | Picu efek kamera **Blur Noises** secara manual |
| **Tombol `N` / `P`** | Keyboard | Ganti filter manual (*Next / Previous*) |
| **Tombol `S`** | Keyboard | Screenshot layar manual |
| **Tombol `TAB`** | Keyboard | Beralih indeks kamera (*Kamera 0 ↔ Kamera 1*) |
| **Tombol `Q` / `ESC`** | Keyboard | Keluar dari aplikasi |

---

## 🚀 Instalasi & Menjalankan

### 1. Kloning Repositori
```bash
git clone https://github.com/Dhammmm11/retrolens-handtrack.git
cd retrolens-handtrack
```

### 2. Pasang Dependensi
```bash
pip install -r requirements.txt
```

### 3. Jalankan Aplikasi
```bash
python handtrack.py
```

*Catatan: Pada saat pertama kali dijalankan, model bobot `hand_landmarker.task` akan diunduh secara otomatis dari Google MediaPipe Repository.*

---

## 📂 Struktur Repositori

```
retrolens-handtrack/
├── handtrack.py         # Skrip utama engine & pemrosesan gestur
├── requirements.txt     # Daftar dependensi Python
├── .gitignore           # Aturan pengabaian file privasi & cache
├── LICENSE              # Lisensi Open-Source MIT
└── README.md            # Dokumentasi proyek
```

---

## 📜 Lisensi

Proyek ini dilisensikan di bawah **MIT License** © 2026 Dhammmm11.
Lihat file [LICENSE](LICENSE) untuk informasi lebih lengkap.
