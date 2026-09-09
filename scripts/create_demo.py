"""Generate visibly synthetic fixtures. Never uses company data or overwrites a folder."""
import argparse
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def board(width, height, x, y, seed, query=False):
    rng = random.Random(seed)
    image = Image.new("RGB", (width, height), (44, 48, 48))
    draw = ImageDraw.Draw(image)
    for row in range(15, height, 33):
        for col in range(12, width, 33):
            shade = rng.randint(65, 90)
            draw.rectangle((col, row, col + 17, row + 17), fill=(shade, shade + 3, shade + 1), outline=(112, 117, 112))
            draw.rectangle((col + 4, row + 4, col + 13, row + 13), fill=(37, 42, 40))
    for j in range(5):
        yy = 55 + j * 69
        draw.line([(0, yy), (90 + j * 35, yy), (140 + j * 35, yy + 37), (width, yy + 37)], fill=(120, 125, 116), width=3)
        draw.line([(0, yy + 7), (86 + j * 35, yy + 7), (136 + j * 35, yy + 44), (width, yy + 44)], fill=(81, 90, 83), width=2)
    draw.rectangle((x - 62, y - 62, x + 62, y + 62), fill=(31, 37, 35), outline=(134, 139, 121), width=2)
    draw.rectangle((x - 45, y - 45, x + 45, y + 45), fill=(81, 91, 82), outline=(148, 156, 133), width=3)
    for offset in [-29, -15, 0, 15, 29]:
        draw.rectangle((x + offset - 3, y - 60, x + offset + 3, y - 47), fill=(165, 169, 144))
        draw.rectangle((x + offset - 3, y + 47, x + offset + 3, y + 60), fill=(165, 169, 144))
        draw.rectangle((x - 60, y + offset - 3, x - 47, y + offset + 3), fill=(165, 169, 144))
        draw.rectangle((x + 47, y + offset - 3, x + 60, y + offset + 3), fill=(165, 169, 144))
    draw.ellipse((x - 18, y - 18, x + 18, y + 18), fill=(49, 58, 52), outline=(156, 170, 143), width=3)
    draw.line((x - 10, y, x + 10, y), fill=(174, 182, 159), width=2)
    draw.line((x, y - 10, x, y + 10), fill=(174, 182, 159), width=2)
    draw.rectangle((0, height - 25, width, height), fill=(31, 40, 37))
    draw.text((12, height - 18), f"SYNTHETIC TEST IMAGE / {'QUERY' if query else 'REF'} / {seed:03d}", fill=(141, 164, 143))
    return image.filter(ImageFilter.GaussianBlur(.25 if query else .1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("sample-data/Dada"))
    parser.add_argument("--markings", action="store_true", help="Draw white boxes/crosses for cleanup verification")
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists():
        raise SystemExit(f"Refusing to overwrite existing directory: {root}")
    for i in range(1, 9):
        folder = root / f"demo_pair_{i:03d}"
        folder.mkdir(parents=True)
        reference = board(512, 512, 256, 241, i)
        x, y = 155 + (i * 37) % 190, 155 + (i * 53) % 190
        query = board(512, 512, x, y, i, True)
        if args.markings:
            ImageDraw.Draw(reference).rectangle((156, 141, 356, 341), outline=(255, 255, 255), width=1)
            draw = ImageDraw.Draw(query)
            draw.line((0, y, 511, y), fill=(255, 255, 255), width=1)
            draw.line((x, 0, x, 511), fill=(255, 255, 255), width=1)
        reference.save(folder / f"sample_{i:03d}_REF.png")
        query.save(folder / f"sample_{i:03d}.png")
    print(f"Created 8 synthetic pairs: {root}")
    print("These images verify the tool only; they do not measure model accuracy.")


if __name__ == "__main__":
    main()
