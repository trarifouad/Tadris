"""Cut static font files from the Google Fonts variable fonts.

Qt selects weights inside variable fonts unevenly across platforms, so the app
ships one static file per weight. Run this only when updating the fonts:

    pip install fonttools
    python scripts/build_fonts.py path/to/ReadexPro[HEXP,wght].ttf path/to/ReemKufi[wght].ttf

IBM Plex Mono is already published as static files; copy Regular and Medium as is.
"""

import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

OUT = Path(__file__).resolve().parents[1] / "src" / "tadris" / "ui" / "resources" / "fonts"

WEIGHTS = {
    "ReadexPro": {400: "Regular", 500: "Medium", 600: "SemiBold"},
    "ReemKufi": {600: "SemiBold", 700: "Bold"},
}


def build(variable_path: Path) -> None:
    family = next(name for name in WEIGHTS if variable_path.name.startswith(name))
    for weight, style in WEIGHTS[family].items():
        font = TTFont(variable_path)
        axes = {axis.axisTag: axis.defaultValue for axis in font["fvar"].axes}
        axes["wght"] = weight
        static = instantiateVariableFont(font, axes, updateFontNames=True)
        static["OS/2"].usWeightClass = weight
        target = OUT / f"{family}-{style}.ttf"
        static.save(target)
        print(f"wrote {target.relative_to(OUT.parents[3])}")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for arg in sys.argv[1:]:
        build(Path(arg))
