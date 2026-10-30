"""Generate Merak's two theme icons and Windows ICO from shared geometry."""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
FACETS = [
    [(48, 191), (83, 87), (128, 131), (128, 169), (95, 137), (77, 191)],
    [(128, 131), (173, 87), (208, 191), (179, 191), (161, 137), (128, 169)],
    [(128, 27), (136, 49), (158, 57), (136, 65),
     (128, 87), (120, 65), (98, 57), (120, 49)],
]
PALETTES = {
    'dark': ('#101b30', '#edf4ff', '#7baaff', '#66e3ef'),
    'light': ('#ffffff', '#142b50', '#346de3', '#089bac'),
}


def render_icon(theme: str) -> Image.Image:
    """Use the same M facets and guiding star in vector and raster output."""
    scale = 4
    image = Image.new('RGBA', (256 * scale, 256 * scale))
    draw = ImageDraw.Draw(image)
    background, *colors = PALETTES[theme]
    border = '#e2e8f0' if theme == 'light' else '#22334f'
    draw.rounded_rectangle((scale, scale, 255 * scale, 255 * scale),
                           radius=55 * scale, fill=background, outline=border, width=2 * scale)
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">',
        '  <title>Merak — NorthS Team</title>',
        f'  <rect x="1" y="1" width="254" height="254" rx="55" '
        f'fill="{background}" stroke="{border}" stroke-width="2"/>',
    ]
    for points, color in zip(FACETS, colors):
        draw.polygon([(x * scale, y * scale) for x, y in points], fill=color)
        coordinates = ' '.join(f'{x},{y}' for x, y in points)
        svg.append(f'  <polygon points="{coordinates}" fill="{color}"/>')
    svg.append('</svg>')
    name = 'icon-light.svg' if theme == 'light' else 'icon.svg'
    (ROOT / 'resources' / name).write_text('\n'.join(svg) + '\n', encoding='utf-8')
    return image.resize((256, 256), Image.Resampling.LANCZOS)


def generate_icons() -> None:
    """Keep the native app icon legible on both light and dark desktops."""
    render_icon('light')
    render_icon('dark').save(
        ROOT / 'resources/icon.ico', sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)],
    )


if __name__ == '__main__':
    generate_icons()
