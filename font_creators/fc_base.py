"""Abstract base class for font format creators. Port of FC_Base.cs."""
from __future__ import annotations

from font_optimizer import FontOptimizer, WidthTarget


class FCBase:
    NAME = 'FCBase'

    def __init__(self, fo: FontOptimizer):
        self._fo = fo
        self.name: str = fo.font_name
        self.font_name_created: str = fo.font_name
        self.width: int = int(fo._font_size + 0.5)  # preliminary, like original
        self.height: int = int(fo.final_height)
        self.monospace: bool = True
        self.first_char: str = ' '
        self.char_count: int = 0
        self.code_size: int = 0

    def mod_name(self) -> str:
        """Generate a C-identifier-safe name. Mirrors FCBase.ModName()."""
        ret = self.name
        for ch in (' ', '-', '+', '%', '(', ')', ',', ';'):
            ret = ret.replace(ch, '_')
        if self.monospace:
            ret += 'x' + str(self.width)
        ret += str(self.height)
        if self._fo.bold:
            ret += '_b'
        if self._fo.italic:
            ret += '_i'
        first_ord = ord(self.first_char)
        last_ord = first_ord + self.char_count - 1
        ret += f'_{first_ord:03d}'
        ret += f'_{last_ord:03d}'
        return ret

    @staticmethod
    def _hex_byte(b: int) -> str:
        return f'0x{b & 0xFF:02x}, '

    @staticmethod
    def _hex_word(w: int) -> str:
        """Format a 16-bit value as two hex bytes, MSB first."""
        return FCBase._hex_byte((w >> 8) & 0xFF) + FCBase._hex_byte(w & 0xFF)

    # ------------------------------------------------------------------
    # Abstract interface – subclasses must implement these
    # ------------------------------------------------------------------

    def letter_factory(self):
        raise NotImplementedError

    def font_file(self, first_char: str, char_count: int,
                  width_target: WidthTarget) -> str:
        raise NotImplementedError

    def _header(self) -> str:
        raise NotImplementedError

    def _descriptor(self) -> str:
        raise NotImplementedError

    def _code_start(self, total_size: int) -> str:
        raise NotImplementedError

    def _trailer(self) -> str:
        raise NotImplementedError
