"""
GLCD FC2-Compatible font creator.

Faithful port of GLCD_FC2_Compatible.cs.
Generates Arduino GLCD-compatible C header files.

Encoding format
---------------
  Bytes are stored page-major, column-minor:
    for each 8-pixel vertical page (b = 0, 1, ...):
      for each column x (left -> right):
        one byte: bit 0 = top pixel of the page, bit 7 = bottom pixel
  The "overrun shift" bug from FontCreator 2.x is intentionally preserved.
"""
from __future__ import annotations

from datetime import date

from font_optimizer import FontOptimizer, WidthTarget, BLANKTX
from font_creators.fc_base import FCBase


# ---------------------------------------------------------------------------
# Letter – encodes one character bitmap
# ---------------------------------------------------------------------------

class Letter:
    def __init__(self):
        self._bytes: list = []
        self._bytes_per_col: int = 1
        self._char: str = ' '

    def create_char(self, c: str, fo: FontOptimizer,
                    width_target: WidthTarget) -> tuple:
        """Digitise character *c*. Returns (width, height) of bitmap used."""
        self._char = c
        img = fo.get_map_for_char(c, width_target)
        w, h = img.size
        pixels = img.load()

        self._bytes = []
        self._bytes_per_col = (h + 7) // 8  # Number of 8-pixel pages

        for b in range(self._bytes_per_col):          # Outer: pages top -> bottom
            for x in range(w):                        # Inner: columns left -> right
                col_byte = 0
                bit = 1
                for y in range(b * 8, (b + 1) * 8):
                    if y < h:
                        if pixels[x, y][0] > BLANKTX:
                            col_byte |= bit
                        bit = (bit << 1) & 0xFF
                    else:
                        # Intentional FC2 "bug": shift in when past bottom
                        col_byte = (col_byte << 1) & 0xFF
                self._bytes.append(col_byte)

        img.close()
        return w, h

    def get_bytes(self) -> str:
        """Return pretty-printed hex string for this character."""
        n = len(self._bytes)
        items_per_line = n // self._bytes_per_col  # = width (one line per page)
        ret = ''
        per_line = 0
        total_out = 0
        for b in self._bytes:
            if per_line % items_per_line == 0:
                ret += '\t'
            ret += f'0x{b:02x}, '
            per_line += 1
            total_out += 1
            if per_line % items_per_line == 0:
                if total_out < n:
                    ret += ' \n'
                per_line = 0

        char_ord = ord(self._char)
        disp = self._char if 32 <= char_ord < 127 else '?'
        ret += f"  // char ({char_ord:03d}) '{disp}'\n\n"
        return ret

    @property
    def byte_count(self) -> int:
        return len(self._bytes)


# ---------------------------------------------------------------------------
# SizeTable – per-character width table for variable-width fonts
# ---------------------------------------------------------------------------

class SizeTable:
    def __init__(self):
        self._widths: list = []

    def add(self, width: int):
        self._widths.append(width & 0xFF)

    @property
    def count(self) -> int:
        return len(self._widths)

    def get_bytes(self) -> str:
        ret = '\n\t// char widths\n'
        per_line = 0
        n = len(self._widths)
        for b in self._widths:
            if per_line % 16 == 0:
                ret += '\t'
            ret += f'0x{b:02x}, '
            per_line += 1
            if per_line % 16 == 0:
                if per_line < n:
                    ret += ' \n'
                per_line = 0
        ret += '\n'
        return ret


# ---------------------------------------------------------------------------
# GLCD_FC2_Compatible – main creator class
# ---------------------------------------------------------------------------

class GLCD_FC2_Compatible(FCBase):
    NAME = 'GLCD_FC2_compatible'

    def __init__(self, fo: FontOptimizer):
        super().__init__(fo)
        self._letters: list = []
        self._size_table = SizeTable()
        self._max_w: int = 0
        self._max_h: int = 0

    def letter_factory(self) -> Letter:
        return Letter()

    def font_file(self, first_char: str, char_count: int,
                  width_target: WidthTarget) -> str:
        """Generate and return the complete .h file content as a string."""
        self.first_char = first_char
        self.char_count = char_count
        self._letters = []
        self._size_table = SizeTable()
        self._max_w = 0
        self._max_h = 0

        first_size = None
        self.monospace = True

        first_ord = ord(first_char)
        for i in range(char_count):
            c = chr(first_ord + i)
            letter = self.letter_factory()
            w, h = letter.create_char(c, self._fo, width_target)
            if first_size is None:
                first_size = (w, h)
            if (w, h) != first_size:
                self.monospace = False
            self._max_w = max(self._max_w, w)
            self._max_h = max(self._max_h, h)
            self._letters.append(letter)
            self._size_table.add(w)

        self.width = self._max_w
        self.height = self._max_h

        code_bytes = sum(l.byte_count for l in self._letters)
        total_size = 6  # Descriptor: size(2) + width(1) + height(1) + first(1) + count(1)
        if not self.monospace:
            total_size += self._size_table.count
        total_size += code_bytes
        self.code_size = total_size

        self.font_name_created = self.mod_name()

        ret = self._header()
        ret += self._descriptor()
        ret += self._code_start(total_size)
        if not self.monospace:
            ret += self._size_table.get_bytes()
        ret += self._letters_bytes()

        # Remove the trailing comma from the very last hex byte
        lc = ret.rfind(',')
        if lc != -1:
            ret = ret[:lc] + ret[lc + 1:]

        ret += self._trailer()
        return ret

    def _letters_bytes(self) -> str:
        ret = '\n\t// font data\n'
        for letter in self._letters:
            ret += letter.get_bytes()
        return ret

    def _header(self) -> str:
        first_ord = ord(self.first_char)
        last_ord = first_ord + self.char_count - 1
        last_disp = chr(last_ord) if 32 <= last_ord < 127 else '?'
        first_disp = self.first_char if 32 <= first_ord < 127 else '?'
        today = date.today().strftime('%m/%d/%Y')

        ret = '//\n'
        ret += f'// Created by {self.NAME} on {today}\n'
        ret += '//\n'
        ret += f'//   Font Name:  {self.font_name_created}\n'
        ret += f'//   Orig. Name: {self.name}\n'
        ret += '//\n'
        ret += f"//   Start Char: {first_ord:03d} '{first_disp}'\n"
        ret += f"//   End Char:   {last_ord:03d} '{last_disp}'\n"
        ret += f'//   # Chars:    {self.char_count}\n'
        ret += '//\n'
        ret += f'//   Height:     {self.height}\n'
        ret += f'//   Width:      {self.width}\n'
        ret += '//\n'
        ret += f'//   Monospace:  {self.monospace}\n'
        ret += f'//   Bold:       {self._fo.bold}\n'
        ret += f'//   Italic:     {self._fo.italic}\n'
        ret += '//\n'
        ret += f'//   Codesize:   {self.code_size}\n'
        ret += '//\n'
        return ret

    def _descriptor(self) -> str:
        mod_upper = self.name.upper().replace(' ', '_')
        ret = '#include <inttypes.h>\n'
        ret += '#include <avr/pgmspace.h>\n'
        ret += '\n'
        ret += f'#ifndef _{mod_upper}_H_\n'
        ret += f'#define _{mod_upper}_H_\n'
        ret += '\n'
        ret += f'#define {mod_upper}_WIDTH  {self.width:<3}\n'
        ret += f'#define {mod_upper}_HEIGHT {self.height:<3}\n'
        ret += '\n'
        return ret

    def _code_start(self, total_size: int) -> str:
        ret = f'static const uint8_t {self.font_name_created}[] PROGMEM = {{\n'
        if self.monospace:
            ret += f'\t{self._hex_word(0)} // size is 0 - Monospace font\n'
        else:
            ret += f'\t{self._hex_word(total_size)} // size\n'
        ret += f'\t{self._hex_byte(self.width)} // width\n'
        ret += f'\t{self._hex_byte(self.height)} // height\n'
        ret += f'\t{self._hex_byte(ord(self.first_char))} // first char\n'
        ret += f'\t{self._hex_byte(self.char_count)} // char count\n'
        ret += '\n'
        return ret

    def _trailer(self) -> str:
        return '\n};\n\n#endif\n\n'
