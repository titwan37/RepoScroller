"""Generate premium high-resolution icons and favicons for RepoScroller.

Theme:
  Administrative Document Repository Scroller - ALCOA+ Compliant
  Palette: Obsidian Navy (#090D16), Indigo (#6366F1), Cyan (#06B6D4), Emerald (#10B981), Amber (#F59E0B)
"""

from pathlib import Path
# pyrefly: ignore [missing-import]
from PIL import Image, ImageDraw, ImageFilter


def create_reposcroller_icon() -> Image.Image:
    # 1. Render at 1024x1024 supersampled canvas for ultra-crisp scaling
    size = 1024
    img = Image.new("RGBA", (size, size), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background Squircle: Deep Obsidian with subtle indigo tone
    bg_pad = 32
    squircle_rect = [bg_pad, bg_pad, size - bg_pad, size - bg_pad]
    draw.rounded_rectangle(
        squircle_rect,
        radius=210,
        fill=(10, 15, 26, 255),
        outline=(99, 102, 241, 230),  # Indigo accent
        width=14,
    )

    # Inner cyber border ring (Cyan glow)
    inner_pad = 52
    draw.rounded_rectangle(
        [inner_pad, inner_pad, size - inner_pad, size - inner_pad],
        radius=190,
        outline=(6, 182, 212, 100),  # Cyan
        width=4,
    )

    # Radar / Scroller Arcs (representing multi-mount document scanning)
    cx, cy = size // 2, size // 2 - 30
    draw.arc([cx - 360, cy - 360, cx + 360, cy + 360], start=205, end=335, fill=(6, 182, 212, 120), width=6)
    draw.arc([cx - 400, cy - 400, cx + 400, cy + 400], start=215, end=325, fill=(99, 102, 241, 90), width=4)
    draw.arc([cx - 320, cy - 320, cx + 320, cy + 320], start=25, end=155, fill=(16, 185, 129, 120), width=6)

    # ── Central Administrative Document / Scroll ──
    # Document dimensions
    doc_w = 400
    doc_h = 510
    doc_x0 = cx - (doc_w // 2)
    doc_y0 = cy - (doc_h // 2) + 20
    doc_x1 = doc_x0 + doc_w
    doc_y1 = doc_y0 + doc_h

    # Shadow under document
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow)
    s_draw.rounded_rectangle(
        [doc_x0 - 8, doc_y0 + 12, doc_x1 + 8, doc_y1 + 24],
        radius=28,
        fill=(0, 0, 0, 160),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    img.alpha_composite(shadow)
    draw = ImageDraw.Draw(img)

    # Document base parchment (Parchment slate gradient fill)
    doc_rect = [doc_x0, doc_y0, doc_x1, doc_y1]
    draw.rounded_rectangle(
        doc_rect,
        radius=26,
        fill=(22, 32, 53, 255),  # Deep slate card
        outline=(241, 245, 249, 180),  # White-slate rim
        width=6,
    )

    # Folded top-right corner of the administrative document
    fold_size = 90
    draw.polygon(
        [
            (doc_x1 - fold_size, doc_y0),
            (doc_x1, doc_y0 + fold_size),
            (doc_x1 - fold_size, doc_y0 + fold_size),
        ],
        fill=(30, 43, 69, 255),
        outline=(6, 182, 212, 200),
    )

    # Document Header Bar (representing structured metadata / hash header)
    draw.rounded_rectangle(
        [doc_x0 + 36, doc_y0 + 44, doc_x1 - fold_size - 24, doc_y0 + 72],
        radius=8,
        fill=(99, 102, 241, 220),  # Indigo title bar
    )

    # Administrative Document Lines (simulating text, ledger rows & integrity hashes)
    line_y = doc_y0 + 110
    line_spacing = 38
    for i in range(7):
        # alternate line widths for natural document ledger look
        if i == 0:
            lw = doc_w - 72
            color = (6, 182, 212, 220)  # Cyan sub-heading
        elif i in (1, 3, 5):
            lw = doc_w - 110
            color = (148, 163, 184, 180)  # Slate text
        elif i == 6:
            lw = 160  # Short concluding signature line
            color = (245, 158, 11, 220)  # Amber signature cue
        else:
            lw = doc_w - 80
            color = (148, 163, 184, 160)

        draw.rounded_rectangle(
            [doc_x0 + 36, line_y, doc_x0 + 36 + lw, line_y + 14],
            radius=6,
            fill=color,
        )
        line_y += line_spacing

    # ── ALCOA+ Compliant Emerald Seal Badge (Bottom Right) ──
    seal_r = 135
    seal_cx = doc_x1 - 10
    seal_cy = doc_y1 - 10

    # Seal outer glow
    seal_glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sg_draw = ImageDraw.Draw(seal_glow)
    sg_draw.ellipse(
        [seal_cx - seal_r - 12, seal_cy - seal_r - 12, seal_cx + seal_r + 12, seal_cy + seal_r + 12],
        fill=(16, 185, 129, 80),
    )
    seal_glow = seal_glow.filter(ImageFilter.GaussianBlur(18))
    img.alpha_composite(seal_glow)
    draw = ImageDraw.Draw(img)

    # Seal outer ring (Gold)
    draw.ellipse(
        [seal_cx - seal_r, seal_cy - seal_r, seal_cx + seal_r, seal_cy + seal_r],
        fill=(16, 185, 129, 255),  # Emerald green base
        outline=(245, 158, 11, 255),  # Gold rim
        width=10,
    )

    # Inner concentric ring
    inner_seal_r = seal_r - 22
    draw.ellipse(
        [seal_cx - inner_seal_r, seal_cy - inner_seal_r, seal_cx + inner_seal_r, seal_cy + inner_seal_r],
        outline=(255, 255, 255, 160),
        width=4,
    )

    # White Checkmark + PLUS symbol (ALCOA+)
    # Bold Checkmark
    chk_w = 16
    draw.line([(seal_cx - 68, seal_cy + 2), (seal_cx - 26, seal_cy + 46)], fill=(255, 255, 255, 255), width=chk_w)
    draw.line([(seal_cx - 26, seal_cy + 46), (seal_cx + 42, seal_cy - 44)], fill=(255, 255, 255, 255), width=chk_w)

    # Plus "+" badge in gold representing the "+" in ALCOA+
    plus_cx = seal_cx + 54
    plus_cy = seal_cy - 48
    pw = 28
    pth = 10
    draw.rounded_rectangle([plus_cx - pw, plus_cy - pth, plus_cx + pw, plus_cy + pth], radius=4, fill=(245, 158, 11, 255))
    draw.rounded_rectangle([plus_cx - pth, plus_cy - pw, plus_cx + pth, plus_cy + pw], radius=4, fill=(245, 158, 11, 255))

    return img


def main():
    root = Path(__file__).resolve().parent.parent
    frontend_dir = root / "frontend"
    public_dir = frontend_dir / "public"

    frontend_dir.mkdir(parents=True, exist_ok=True)
    public_dir.mkdir(parents=True, exist_ok=True)

    print("Generating high-resolution master icon (1024x1024)...")
    master = create_reposcroller_icon()

    # Targets to save
    sizes = {
        "icon-512.png": 512,
        "icon-192.png": 192,
        "apple-touch-icon.png": 180,
        "favicon-64.png": 64,
        "favicon-32.png": 32,
        "favicon.png": 64,
    }

    print("Rendering downscaled sizes with Lanczos antialiasing...")
    for filename, s in sizes.items():
        resized = master.resize((s, s), Image.Resampling.LANCZOS)
        # Save to both frontend root and frontend/public
        resized.save(frontend_dir / filename)
        resized.save(public_dir / filename)
        print(f"  [OK] Saved {filename} ({s}x{s})")

    # Generate multi-resolution .ico file
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64)]
    ico_images = [master.resize(s, Image.Resampling.LANCZOS) for s in ico_sizes]

    ico_path_1 = frontend_dir / "favicon.ico"
    ico_path_2 = public_dir / "favicon.ico"

    ico_images[0].save(
        ico_path_1,
        format="ICO",
        sizes=ico_sizes,
        append_images=ico_images[1:],
    )
    ico_images[0].save(
        ico_path_2,
        format="ICO",
        sizes=ico_sizes,
        append_images=ico_images[1:],
    )
    print("  [OK] Saved favicon.ico (multi-res 16, 24, 32, 48, 64)")

    print("\nRepoScroller ALCOA+ Compliant icons generated successfully!")


if __name__ == "__main__":
    main()
