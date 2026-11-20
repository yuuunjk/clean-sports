#!/usr/bin/env python3
"""LUKA 스포츠 앱 아이콘 생성기 (PWA / 삼성 인터넷 웹앱 설치용).

가운데 축구공이 있는 파란 그라데이션 아이콘을 512·192·180 PNG로 만든다.
maskable 아이콘 규격(안전 영역 80% 원 안)에 맞춰 공을 68% 크기로 배치한다.
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIZE = 512
SS = 4  # 슈퍼샘플링 배율


def lerp(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def background(size):
    """왼쪽 위 파랑 → 오른쪽 아래 청록 그라데이션 + 위쪽 하이라이트."""
    top = (37, 99, 235)
    bottom = (14, 165, 168)
    img = Image.new("RGB", (size, size), top)
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x / size * 0.45) + (y / size * 0.55)
            px[x, y] = lerp(top, bottom, min(max(t, 0.0), 1.0))
    glow = Image.new("L", (size, size), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-size * 0.25, -size * 0.55, size * 0.95, size * 0.45], fill=70)
    glow = glow.filter(ImageFilter.GaussianBlur(size * 0.12))
    white = Image.new("RGB", (size, size), (255, 255, 255))
    return Image.composite(white, img, glow)


def pentagon(cx, cy, r, rot=-90):
    pts = []
    for i in range(5):
        a = math.radians(rot + i * 72)
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def draw_ball(canvas, cx, cy, radius):
    """공을 별도 레이어에 그린 뒤 원으로 잘라 얹는다(오각형이 원 밖으로 나가지 않게)."""
    size = canvas.size[0]
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=(255, 255, 255))
    # 가운데 검은 오각형
    d.polygon(pentagon(cx, cy, radius * 0.33, -90), fill=(20, 33, 56, 255))
    # 둘레 오각형 5개 (원 가장자리에 걸치도록)
    for i in range(5):
        a = math.radians(-90 + i * 72)
        px = cx + radius * 0.70 * math.cos(a)
        py = cy + radius * 0.70 * math.sin(a)
        d.polygon(pentagon(px, py, radius * 0.31, -90 + i * 72), fill=(20, 33, 56, 255))
    # 이음선
    for i in range(5):
        a = math.radians(-90 + i * 72 + 36)
        x1 = cx + radius * 0.33 * math.cos(a)
        y1 = cy + radius * 0.33 * math.sin(a)
        x2 = cx + radius * 1.05 * math.cos(a)
        y2 = cy + radius * 1.05 * math.sin(a)
        d.line([(x1, y1), (x2, y2)], fill=(20, 33, 56, 255), width=max(2, int(radius * 0.07)))
    # 원 안으로 자르기
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=255)
    clipped = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    clipped.paste(layer, (0, 0), mask)

    # 부드러운 그림자
    sh = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse(
        [cx - radius, cy - radius + radius * 0.10, cx + radius, cy + radius + radius * 0.10],
        fill=(8, 30, 70, 110),
    )
    sh = sh.filter(ImageFilter.GaussianBlur(radius * 0.09))
    canvas.alpha_composite(sh)
    canvas.alpha_composite(clipped)
    # 테두리
    ImageDraw.Draw(canvas).ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        outline=(20, 33, 56, 255), width=max(2, int(radius * 0.045)),
    )


def build(size=SIZE):
    big = background(size * SS).convert("RGBA")
    cx = cy = big.size[0] / 2
    # 안전 영역(80%) 안에 들어오도록 지름 68%
    draw_ball(big, cx, cy, big.size[0] * 0.34)
    return big.resize((size, size), Image.LANCZOS).convert("RGB")


def main():
    master = build(SIZE)
    outputs = {"app-icon-512.png": 512, "app-icon-192.png": 192, "app-icon-180.png": 180}
    for name, px in outputs.items():
        img = master if px == 512 else master.resize((px, px), Image.LANCZOS)
        path = os.path.join(ROOT, name)
        img.save(path, "PNG", optimize=True)
        print(f"{name}: {px}x{px}, {os.path.getsize(path)/1024:.1f} KB")


if __name__ == "__main__":
    main()
