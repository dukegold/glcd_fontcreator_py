"""
Port of FontOptimizer.cs from GLCD_FontCreator.

Uses Pillow for font rendering instead of Windows GDI+.
Algorithm is a faithful translation of the original C# logic.
"""
from __future__ import annotations

import glob
import os
import sys
from dataclasses import dataclass
from enum import IntEnum

from PIL import Image, ImageDraw, ImageFont

BLANKTX = 20  # Red-channel values <= this are treated as background pixels


class WidthTarget(IntEnum):
    WT_NONE = 0     # Full character width as given by font metrics
    WT_MONO = 1     # Same minimum width for all chars (monospace-like)
    WT_MINIMUM = 2  # Individual minimum width per character


@dataclass
class Rect:
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    @property
    def right(self) -> int:
        return self.x + self.width - 1

    @property
    def bottom(self) -> int:
        return self.y + self.height - 1

    def union(self, other: Rect) -> Rect:
        x = min(self.x, other.x)
        y = min(self.y, other.y)
        right = max(self.right, other.right)
        bottom = max(self.bottom, other.bottom)
        return Rect(x, y, right - x + 1, bottom - y + 1)


class FontOptimizer:
    BLANKTX = BLANKTX

    def __init__(self, font_path: str, font_name: str = '',
                 bold: bool = False, italic: bool = False):
        self.font_path = font_path
        self.font_name = font_name or os.path.splitext(os.path.basename(font_path))[0]
        self.bold = bold
        self.italic = italic

        # Input parameters (set by caller before optimize())
        self.first_char: str = ' '
        self.char_count: int = 10
        self.target_height: int = 16
        self.remove_top: bool = False
        self.remove_bottom: bool = False

        # Output (populated by optimize())
        self.font_to_use: ImageFont.FreeTypeFont = self._load_font(16)
        self.scanline_start: int = 0
        self.scanline_end: int = 0
        self.final_height: int = 0
        self.minimum_rect: Rect = Rect()
        self._font_size: float = 16.0

    # ------------------------------------------------------------------
    # Internal rendering helpers
    # ------------------------------------------------------------------

    def _load_font(self, size: float) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(self.font_path, max(4, int(round(size))))

    def _get_string_bitmap(self, pil_font: ImageFont.FreeTypeFont,
                           text: str) -> Image.Image:
        """Render *text* as red-on-black; mirrors GDI+ GetStringBitmap."""
        dummy = Image.new('RGB', (1, 1))
        draw = ImageDraw.Draw(dummy)
        try:
            bbox = draw.textbbox((0, 0), text, font=pil_font)
        except AttributeError:
            # Pillow < 8.0 fallback
            w, h = draw.textsize(text, font=pil_font)
            bbox = (0, 0, w, h)

        # Handle negative left bearing (e.g. italic glyphs)
        x_off = max(0, -bbox[0])
        w = max(bbox[2] + x_off + 2, 2)
        h = max(bbox[3] + 2, 2)

        img = Image.new('RGB', (w, h), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text((x_off, 0), text, font=pil_font, fill=(255, 0, 0))
        return img

    def _get_minimum_height_rect(self, img: Image.Image) -> tuple:
        """Return (scanline_start, scanline_end) of rendered content rows."""
        width, height = img.size
        pixels = img.load()

        scanline_start = 0
        scanline_end = 0

        for y in range(height):
            blank_line = True
            for x in range(width):
                if pixels[x, y][0] >= BLANKTX:
                    blank_line = False
                    break

            # Advance start past blank top rows (only while no content seen yet)
            if blank_line and scanline_end == 0:
                scanline_start = y
            if not blank_line:
                scanline_end = y  # Track last non-blank row

        # scanline_start is the last blank row before content; take the next one
        scanline_start += 1

        if scanline_end == 0:
            # No painted rows at all
            scanline_start = height // 2
            scanline_end = scanline_start

        return scanline_start, scanline_end

    def _get_minimum_width_rect(self, img: Image.Image) -> Rect:
        """Return Rect with horizontal bounds of rendered content columns."""
        width, height = img.size
        pixels = img.load()

        scan_col_start = 0
        scan_col_end = 0

        for x in range(width):
            blank_col = True
            for y in range(height):
                if pixels[x, y][0] >= BLANKTX:
                    blank_col = False
                    break

            if blank_col and scan_col_end == 0:
                scan_col_start = x  # Advance past left blank columns
            if not blank_col:
                scan_col_end = x  # Track last non-blank column

        scan_col_start += 1  # Last blank col; take the next one

        if scan_col_end == 0:
            scan_col_start = width // 2
            scan_col_end = scan_col_start

        return Rect(scan_col_start, self.scanline_start,
                    scan_col_end - scan_col_start + 1, self.final_height)

    def _try_font_height(self, pil_font: ImageFont.FreeTypeFont,
                         test_string: str, target_height: int) -> int:
        """Test one font size. Returns deviation (positive=too big, negative=too small)."""
        img = self._get_string_bitmap(pil_font, test_string)
        sl_start, sl_end = self._get_minimum_height_rect(img)

        start_line = sl_start
        end_line = sl_end
        if not self.remove_top:
            start_line = 0
        if not self.remove_bottom:
            end_line = img.height - 1

        height = end_line - start_line + 1

        if height >= target_height:
            self.scanline_start = start_line
            self.scanline_end = end_line
            self.font_to_use = pil_font
            self.final_height = height
            self._font_size = float(pil_font.size)

        return height - target_height

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def optimize(self) -> int:
        """Find the font size that achieves target_height. Returns final delta."""
        first_ord = ord(self.first_char)
        test_string = ''.join(chr(first_ord + i) for i in range(self.char_count))

        f_size = max(self.target_height / 2.0, 4.0)
        try_font = self._load_font(f_size)
        ret_val = self._try_font_height(try_font, test_string, self.target_height)

        while ret_val < 0:
            if ret_val >= -2:
                f_size += 0.125
            elif ret_val == -3:
                f_size += 0.25
            elif ret_val == -4:
                f_size += 0.5
            else:
                f_size += 2.0
            try_font = self._load_font(f_size)
            ret_val = self._try_font_height(try_font, test_string, self.target_height)

        # Establish minimum width info across all characters
        last_char_ord = first_ord + self.char_count - 1
        tmp_rect = Rect(1000, self.scanline_start, 1, self.final_height)
        first = True
        for char_ord in range(first_ord, last_char_ord + 1):
            c = chr(char_ord)
            img = self._get_string_bitmap(self.font_to_use, c)
            if first:
                tmp_rect.x = img.width // 2
                first = False
            w_rect = self._get_minimum_width_rect(img)
            tmp_rect = tmp_rect.union(w_rect)

        self.minimum_rect = tmp_rect
        return ret_val

    def get_map_for_char(self, c: str, width_target: WidthTarget) -> Image.Image:
        """Return a cropped red-on-black bitmap for character *c*."""
        img = self._get_string_bitmap(self.font_to_use, c)

        cut = Rect(self.minimum_rect.x, self.scanline_start,
                   self.minimum_rect.width, self.final_height)

        if width_target == WidthTarget.WT_NONE:
            cut.x = 0
            cut.width = img.width
        elif width_target == WidthTarget.WT_MINIMUM:
            if c == ' ':
                cut.x = 0
                cut.width = img.width
            else:
                w_rect = self._get_minimum_width_rect(img)
                cut.x = w_rect.x
                cut.width = w_rect.width

        # PIL crop: (left, top, right, bottom); auto-pads with black if out of bounds
        box = (cut.x, cut.y, cut.x + cut.width, cut.y + cut.height)
        cropped = img.crop(box)

        # If padding occurred, cropped size matches the requested cut size already.
        # If crop dimensions don't match (edge case), pad manually.
        if cropped.size != (max(cut.width, 1), max(cut.height, 1)):
            padded = Image.new('RGB', (max(cut.width, 1), max(cut.height, 1)), (0, 0, 0))
            padded.paste(cropped, (0, 0))
            return padded

        return cropped

    def make_thumbnail(self, file_path: str):
        """Save a PNG thumbnail of all characters alongside the header file."""
        first_ord = ord(self.first_char)
        test_string = ''.join(chr(first_ord + i) for i in range(self.char_count))
        img = self._get_string_bitmap(self.font_to_use, test_string)
        img.save(file_path + '.png', 'PNG')


# ------------------------------------------------------------------
# System font discovery
# ------------------------------------------------------------------

def get_system_font_dirs() -> list:
    """Return OS-appropriate font directories."""
    if sys.platform == 'win32':
        windir = os.environ.get('WINDIR', r'C:\Windows')
        return [os.path.join(windir, 'Fonts')]
    elif sys.platform == 'darwin':
        return [
            '/System/Library/Fonts',
            '/Library/Fonts',
            os.path.expanduser('~/Library/Fonts'),
        ]
    else:  # Linux / BSD
        return [
            '/usr/share/fonts',
            '/usr/local/share/fonts',
            os.path.expanduser('~/.fonts'),
            os.path.expanduser('~/.local/share/fonts'),
        ]


def find_system_fonts() -> dict:
    """Return {display_name: file_path} for all discoverable TTF/OTF fonts."""
    fonts = {}
    for font_dir in get_system_font_dirs():
        if not os.path.isdir(font_dir):
            continue
        for ext in ('*.ttf', '*.TTF', '*.otf', '*.OTF'):
            for path in glob.glob(os.path.join(font_dir, '**', ext), recursive=True):
                name = os.path.splitext(os.path.basename(path))[0]
                if name not in fonts:
                    fonts[name] = path
    return fonts
