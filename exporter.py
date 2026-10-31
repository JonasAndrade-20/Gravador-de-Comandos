"""Compilação do manual de procedimentos em um arquivo .docx.

O documento gerado contém:

* capa com logotipo, título, empresa e data;
* cabeçalho e rodapé com identidade visual e numeração de páginas;
* cada passo com descrição, imagem centralizada, legenda e observações;
* estilos nomeados (Calibri, azul corporativo) para facilitar ajustes no Word.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.style import WD_STYLE_TYPE
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image

from recorder import button_label

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Identidade visual
# ---------------------------------------------------------------------------
FONT = "Calibri"
FONT_DISPLAY = "Calibri Light"
DEFAULT_ACCENT = "#1F4E79"
TEXT_COLOR = "#1B2430"
MUTED_COLOR = "#5B6777"
BORDER_COLOR = "#D9DEE7"
PAGE_WIDTH_CM = 21.0
CONTENT_WIDTH_CM = 17.0

_ACCENT_RE = re.compile(r"^#?([0-9A-Fa-f]{6})$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_INVALID_FILENAME_RE = re.compile(r"[^A-Za-z0-9._ -]+")


@dataclass(slots=True)
class ManualStep:
    """Dados de um passo já revisados pelo usuário."""

    image_path: str
    description: str = ""
    notes: str = ""
    x: int | None = None
    y: int | None = None
    button: str = "left"
    captured_at: datetime | None = None


@dataclass(slots=True)
class ManualConfig:
    """Configurações do documento."""

    title: str = "Manual de Procedimentos"
    company: str = ""
    subtitle: str = ""
    author: str = ""
    logo: bytes | None = None
    accent_color: str = DEFAULT_ACCENT
    include_metadata: bool = False
    page_break_per_step: bool = False
    generated_at: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Helpers de cor e texto
# ---------------------------------------------------------------------------
def normalize_hex(value: str | None, fallback: str = DEFAULT_ACCENT) -> str:
    match = _ACCENT_RE.match((value or "").strip())
    if not match:
        return fallback
    return "#" + match.group(1).upper()


def _hex_rgb(value: str) -> tuple[int, int, int]:
    value = normalize_hex(value)
    return (int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16))


def _rgb(value: str) -> RGBColor:
    return RGBColor.from_string(normalize_hex(value).lstrip("#"))


def mix_color(value: str, other: str = "#FFFFFF", ratio: float = 0.9) -> str:
    """Mistura ``value`` com ``other`` (ratio 0 = value, 1 = other)."""
    ratio = max(0.0, min(1.0, float(ratio)))
    a = _hex_rgb(value)
    b = _hex_rgb(other)
    return "#" + "".join(
        f"{int(round(a[i] * (1.0 - ratio) + b[i] * ratio)):02X}" for i in range(3)
    )


def _clean(value: object) -> str:
    text = str(value if value is not None else "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub(" ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _short(text: str, limit: int = 90) -> str:
    one_line = " ".join(_clean(text).split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 1].rstrip() + "…"


def safe_filename(value: str, fallback: str = "manual") -> str:
    normalized = unicodedata.normalize("NFKD", _clean(value))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = _INVALID_FILENAME_RE.sub("", ascii_text)
    ascii_text = re.sub(r"\s+", "_", ascii_text).strip("._- ")
    return (ascii_text[:80] or fallback) + ".docx"


def default_filename(config: ManualConfig) -> str:
    return safe_filename(config.title or "Manual de Procedimentos")


# ---------------------------------------------------------------------------
# Helpers de baixo nível do Word
# ---------------------------------------------------------------------------
def _add_field(paragraph, instruction: str, *, size: float = 8.0) -> None:
    """Insere um campo do Word (PAGE, NUMPAGES, SECTIONPAGES...)."""

    def styled_run():
        run = paragraph.add_run()
        run.font.name = FONT
        run.font.size = Pt(size)
        run.font.color.rgb = _rgb(MUTED_COLOR)
        return run

    run = styled_run()
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    run._r.append(fld_begin)

    run = styled_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    run._r.append(instr)

    run = styled_run()
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    run._r.append(fld_sep)

    styled_run().text = "1"

    run = styled_run()
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_end)


def _paragraph_border(
    paragraph,
    edge: str = "bottom",
    color: str = BORDER_COLOR,
    *,
    size: int = 8,
    space: int = 1,
) -> None:
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = p_pr.find(qn("w:pBdr"))
    if p_bdr is None:
        p_bdr = OxmlElement("w:pBdr")
        p_pr.append(p_bdr)
    element = OxmlElement(f"w:{edge}")
    element.set(qn("w:val"), "single")
    element.set(qn("w:sz"), str(max(1, int(size))))
    element.set(qn("w:space"), str(max(0, int(space))))
    element.set(qn("w:color"), normalize_hex(color).lstrip("#"))
    p_bdr.append(element)


def _shade_cell(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = tc_pr.find(qn("w:shd"))
    if shd is None:
        shd = OxmlElement("w:shd")
        tc_pr.append(shd)
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), normalize_hex(fill).lstrip("#"))


def _cell_borders(cell, *, left=None, top=None, right=None, bottom=None) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge, props in (
        ("left", left),
        ("top", top),
        ("right", right),
        ("bottom", bottom),
    ):
        element = borders.find(qn(f"w:{edge}"))
        if element is None:
            element = OxmlElement(f"w:{edge}")
            borders.append(element)
        if props is None:
            element.set(qn("w:val"), "nil")
            element.set(qn("w:color"), "auto")
        else:
            element.set(qn("w:val"), "single")
            element.set(qn("w:sz"), str(max(1, int(props.get("sz", 4)))))
            element.set(qn("w:space"), "0")
            element.set(qn("w:color"), normalize_hex(props.get("color", BORDER_COLOR)).lstrip("#"))


def _cell_margins(
    cell,
    *,
    top: int = 80,
    start: int = 80,
    bottom: int = 80,
    end: int = 80,
) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_mar = tc_pr.find(qn("w:tcMar"))
    if tc_mar is None:
        tc_mar = OxmlElement("w:tcMar")
        tc_pr.append(tc_mar)
    for tag, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        element = OxmlElement(f"w:{tag}")
        element.set(qn("w:w"), str(max(0, int(value))))
        element.set(qn("w:type"), "dxa")
        tc_mar.append(element)


def _table_width(table, width_cm: float = CONTENT_WIDTH_CM) -> None:
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(int(Cm(width_cm).twips)))
    tbl_w.set(qn("w:type"), "dxa")
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    tbl_pr.append(layout)


def _row_no_split(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    cant_split = OxmlElement("w:cantSplit")
    tr_pr.append(cant_split)


def _table_no_borders(table) -> None:
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "nil")
        borders.append(element)
    tbl_pr.append(borders)


def _table_bottom_border(table, color: str, size: int = 8) -> None:
    tbl_pr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        element = OxmlElement(f"w:{edge}")
        if edge == "bottom":
            element.set(qn("w:val"), "single")
            element.set(qn("w:sz"), str(size))
            element.set(qn("w:space"), "0")
            element.set(qn("w:color"), normalize_hex(color).lstrip("#"))
        else:
            element.set(qn("w:val"), "nil")
        borders.append(element)
    tbl_pr.append(borders)


def _add_multiline(paragraph, text: str) -> None:
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if index:
            paragraph.add_run().add_break()
        if line:
            paragraph.add_run(line)


# ---------------------------------------------------------------------------
# Estilos
# ---------------------------------------------------------------------------
def _font_rpr(style):
    r_pr = style.element.rPr
    if r_pr is None:
        r_pr = OxmlElement("w:rPr")
        style.element.append(r_pr)
    return r_pr


def _set_style_font(style, font_name: str = FONT) -> None:
    r_pr = _font_rpr(style)
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.insert(0, r_fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        r_fonts.set(qn(attr), font_name)


def _style_color(style, color: str) -> None:
    style.font.color.rgb = _rgb(color)
    r_pr = _font_rpr(style)
    color_el = r_pr.find(qn("w:color"))
    if color_el is not None:
        for attr in ("themeColor", "themeShade", "themeTint"):
            color_el.attrib.pop(attr, None)


def _set_char_spacing(style, twips: int) -> None:
    r_pr = _font_rpr(style)
    spacing = r_pr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        r_pr.append(spacing)
    spacing.set(qn("w:val"), str(int(twips)))


def _make_style(
    doc,
    name: str,
    *,
    base: str = "Normal",
    size: float,
    color: str,
    bold: bool = False,
    italic: bool = False,
    font: str = FONT,
    before: float = 0,
    after: float = 6,
    line: float | None = 1.15,
    keep_with_next: bool = False,
    alignment=None,
    all_caps: bool = False,
    char_spacing: int | None = None,
):
    try:
        style = doc.styles[name]
    except KeyError:
        style = doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.base_style = doc.styles[base]
    _set_style_font(style, font)
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.italic = italic
    style.font.all_caps = all_caps
    _style_color(style, color)
    paragraph_format = style.paragraph_format
    paragraph_format.space_before = Pt(before)
    paragraph_format.space_after = Pt(after)
    if line is not None:
        paragraph_format.line_spacing = line
    paragraph_format.keep_with_next = keep_with_next
    if alignment is not None:
        paragraph_format.alignment = alignment
    if char_spacing is not None:
        _set_char_spacing(style, char_spacing)
    style.quick_style = True
    return style


def _configure_styles(doc, accent: str) -> None:
    normal = doc.styles["Normal"]
    _set_style_font(normal, FONT)
    normal.font.size = Pt(10.5)
    _style_color(normal, TEXT_COLOR)
    normal.paragraph_format.line_spacing = 1.15
    normal.paragraph_format.space_after = Pt(6)

    heading1 = doc.styles["Heading 1"]
    _set_style_font(heading1, FONT)
    heading1.font.size = Pt(20)
    heading1.font.bold = True
    _style_color(heading1, accent)
    heading1.paragraph_format.space_before = Pt(6)
    heading1.paragraph_format.space_after = Pt(10)
    heading1.paragraph_format.keep_with_next = True
    heading1.paragraph_format.line_spacing = 1.0

    heading2 = doc.styles["Heading 2"]
    _set_style_font(heading2, FONT)
    heading2.font.size = Pt(14)
    heading2.font.bold = True
    _style_color(heading2, accent)
    heading2.paragraph_format.space_before = Pt(14)
    heading2.paragraph_format.space_after = Pt(4)
    heading2.paragraph_format.keep_with_next = True

    _make_style(
        doc,
        "Manual Cover Kicker",
        size=9,
        color=accent,
        bold=True,
        before=0,
        after=4,
        line=1.0,
        char_spacing=50,
    )
    _make_style(
        doc,
        "Manual Cover Title",
        size=31,
        color=TEXT_COLOR,
        bold=True,
        font=FONT_DISPLAY,
        before=0,
        after=6,
        line=1.0,
    )
    _make_style(
        doc,
        "Manual Cover Subtitle",
        size=12.5,
        color=MUTED_COLOR,
        before=0,
        after=0,
        line=1.2,
    )
    _make_style(
        doc,
        "Manual Cover Meta",
        size=9,
        color=MUTED_COLOR,
        before=0,
        after=0,
        line=1.2,
    )
    _make_style(
        doc,
        "Manual Lead",
        size=10.5,
        color=MUTED_COLOR,
        before=0,
        after=14,
        line=1.3,
    )
    _make_style(
        doc,
        "Manual Step Label",
        size=8.5,
        color=accent,
        bold=True,
        before=20,
        after=1,
        line=1.0,
        keep_with_next=True,
        char_spacing=40,
    )
    _make_style(
        doc,
        "Manual Step Title",
        size=13.5,
        color=TEXT_COLOR,
        bold=True,
        before=0,
        after=4,
        line=1.1,
        keep_with_next=True,
    )
    _make_style(
        doc,
        "Manual Meta",
        size=8,
        color=MUTED_COLOR,
        before=0,
        after=6,
        line=1.1,
        keep_with_next=True,
    )
    _make_style(
        doc,
        "Manual Caption",
        size=8.5,
        color=MUTED_COLOR,
        italic=True,
        before=4,
        after=0,
        line=1.0,
        alignment=WD_ALIGN_PARAGRAPH.CENTER,
    )
    _make_style(
        doc,
        "Manual Note Label",
        size=7.5,
        color=accent,
        bold=True,
        before=0,
        after=2,
        line=1.0,
        char_spacing=40,
    )
    _make_style(
        doc,
        "Manual Note Text",
        size=9.5,
        color=TEXT_COLOR,
        before=0,
        after=0,
        line=1.15,
    )
    _make_style(
        doc,
        "Manual Cover Footer",
        size=8.5,
        color=MUTED_COLOR,
        before=0,
        after=0,
        line=1.0,
    )

    # Os estilos nativos Header/Footer trazem paradas de tabulação no centro
    # e à direita. Removê-las permite alinhar o rodapé inteiro à direita.
    for style_name in ("Header", "Footer"):
        try:
            doc.styles[style_name].paragraph_format.tab_stops.clear_all()
        except KeyError:
            pass


# ---------------------------------------------------------------------------
# Imagens e logo
# ---------------------------------------------------------------------------
def _image_size_cm(path: str, max_w_cm: float, max_h_cm: float) -> tuple[float, float]:
    with Image.open(path) as image:
        width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError("Imagem sem dimensões válidas.")
    ratio = min(max_w_cm / width, max_h_cm / height)
    return width * ratio, height * ratio


def _fit_size_cm(
    width: int, height: int, max_w_cm: float, max_h_cm: float
) -> tuple[float, float]:
    ratio = min(max_w_cm / max(1, width), max_h_cm / max(1, height))
    return max(1, width) * ratio, max(1, height) * ratio


def _prepare_logo(logo: bytes | None) -> tuple[bytes, int, int] | None:
    if not logo:
        return None
    try:
        with Image.open(io.BytesIO(logo)) as image:
            image.load()
            width, height = image.size
            if width < 8 or height < 8:
                raise ValueError("Logo muito pequena.")
            converted = image.convert("RGBA")
            output = io.BytesIO()
            converted.save(output, format="PNG", optimize=True)
            return output.getvalue(), width, height
    except Exception as exc:
        logger.warning("Logo ignorada por não ser uma imagem válida: %s", exc)
        return None


def _add_logo(paragraph, logo_png: bytes, width: int, height: int, max_w: float, max_h: float):
    width_cm, height_cm = _fit_size_cm(width, height, max_w, max_h)
    run = paragraph.add_run()
    run.add_picture(io.BytesIO(logo_png), width=Cm(width_cm), height=Cm(height_cm))
    return run


# ---------------------------------------------------------------------------
# Estrutura do documento
# ---------------------------------------------------------------------------
def _configure_section(section) -> None:
    section.page_width = Cm(PAGE_WIDTH_CM)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(3.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)
    section.header_distance = Cm(0.8)
    section.footer_distance = Cm(0.8)


def _build_cover(
    doc,
    config: ManualConfig,
    logo: tuple[bytes, int, int] | None,
    step_count: int,
) -> None:
    accent = normalize_hex(config.accent_color)

    top = doc.add_paragraph()
    top.paragraph_format.space_before = Pt(36)
    top.paragraph_format.space_after = Pt(0)

    if logo is not None:
        logo_png, logo_w, logo_h = logo
        logo_paragraph = doc.add_paragraph()
        logo_paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        logo_paragraph.paragraph_format.space_before = Pt(0)
        logo_paragraph.paragraph_format.space_after = Pt(0)
        _add_logo(logo_paragraph, logo_png, logo_w, logo_h, max_w=8.0, max_h=2.8)
    elif config.company:
        company_paragraph = doc.add_paragraph()
        company_paragraph.paragraph_format.space_before = Pt(0)
        company_paragraph.paragraph_format.space_after = Pt(0)
        run = company_paragraph.add_run(config.company.upper())
        run.font.name = FONT
        run.font.size = Pt(13)
        run.font.bold = True
        run.font.color.rgb = _rgb(accent)

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(110)
    spacer_run = spacer.add_run("")
    spacer_run.font.size = Pt(1)

    kicker = doc.add_paragraph(style="Manual Cover Kicker")
    kicker.add_run("MANUAL DE PROCEDIMENTOS")

    title = doc.add_paragraph(style="Manual Cover Title")
    title.add_run(_clean(config.title) or "Manual de Procedimentos")

    if config.subtitle:
        subtitle = doc.add_paragraph(style="Manual Cover Subtitle")
        subtitle.paragraph_format.space_before = Pt(10)
        subtitle.add_run(_clean(config.subtitle))

    rule = doc.add_paragraph()
    rule.paragraph_format.space_before = Pt(16)
    rule.paragraph_format.space_after = Pt(16)
    rule_run = rule.add_run("")
    rule_run.font.size = Pt(1)
    _paragraph_border(rule, "bottom", accent, size=12, space=1)

    rows: list[tuple[str, str]] = []
    if config.company:
        rows.append(("Empresa", config.company))
    if config.author:
        rows.append(("Elaborado por", config.author))
    rows.append(("Data", config.generated_at.strftime("%d/%m/%Y")))
    rows.append(("Passos documentados", f"{step_count:02d}"))

    table = doc.add_table(rows=0, cols=2)
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    _table_width(table, 13.0)
    _table_no_borders(table)
    for label, value in rows:
        cells = table.add_row().cells
        cells[0].width = Cm(4.2)
        cells[1].width = Cm(8.8)
        cells[0].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        cells[1].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        _cell_margins(cells[0], top=50, bottom=50, start=0, end=80)
        _cell_margins(cells[1], top=50, bottom=50, start=0, end=0)
        label_paragraph = cells[0].paragraphs[0]
        label_paragraph.paragraph_format.space_after = Pt(0)
        label_run = label_paragraph.add_run(label.upper())
        label_run.font.name = FONT
        label_run.font.size = Pt(7.5)
        label_run.font.bold = True
        label_run.font.color.rgb = _rgb(MUTED_COLOR)
        value_paragraph = cells[1].paragraphs[0]
        value_paragraph.paragraph_format.space_after = Pt(0)
        value_run = value_paragraph.add_run(_clean(value) or "—")
        value_run.font.name = FONT
        value_run.font.size = Pt(10)
        value_run.font.color.rgb = _rgb(TEXT_COLOR)

    footer = doc.add_paragraph(style="Manual Cover Footer")
    footer.paragraph_format.space_before = Pt(70)
    footer.add_run(
        "Documento gerado em "
        + config.generated_at.strftime("%d/%m/%Y às %H:%M")
        + "."
    )

    doc.add_section(WD_SECTION.NEW_PAGE)


def _build_header_footer(section, config: ManualConfig, logo, accent: str) -> None:
    header = section.header
    header.is_linked_to_previous = False
    header_paragraph = header.paragraphs[0]
    header_paragraph.paragraph_format.tab_stops.add_tab_stop(
        Cm(CONTENT_WIDTH_CM), WD_TAB_ALIGNMENT.RIGHT
    )
    header_paragraph.paragraph_format.space_after = Pt(2)
    header_paragraph.paragraph_format.line_spacing = 1.0

    if logo is not None:
        logo_png, logo_w, logo_h = logo
        _add_logo(header_paragraph, logo_png, logo_w, logo_h, max_w=5.6, max_h=1.0)
    header_paragraph.add_run("\t")
    top_text = config.company or config.title
    top_run = header_paragraph.add_run(_clean(top_text))
    top_run.font.name = FONT
    top_run.font.size = Pt(8.5)
    top_run.font.bold = True
    top_run.font.color.rgb = _rgb(accent)

    if config.company and config.title:
        header_paragraph.add_run().add_break()
        header_paragraph.add_run("\t")
        bottom_run = header_paragraph.add_run(_short(config.title, 95))
        bottom_run.font.name = FONT
        bottom_run.font.size = Pt(7.5)
        bottom_run.font.color.rgb = _rgb(MUTED_COLOR)
    _paragraph_border(header_paragraph, "bottom", accent, size=8, space=2)

    footer = section.footer
    footer.is_linked_to_previous = False
    footer_paragraph = footer.paragraphs[0]
    footer_paragraph.paragraph_format.tab_stops.add_tab_stop(
        Cm(CONTENT_WIDTH_CM), WD_TAB_ALIGNMENT.RIGHT
    )
    footer_paragraph.paragraph_format.space_before = Pt(2)
    footer_paragraph.paragraph_format.line_spacing = 1.0
    _paragraph_border(footer_paragraph, "top", BORDER_COLOR, size=4, space=3)

    left_text = config.company or config.title
    if config.company and config.title:
        left_text = f"{config.company} · {config.title}"
    left_run = footer_paragraph.add_run(_short(left_text, 80))
    left_run.font.name = FONT
    left_run.font.size = Pt(7.5)
    left_run.font.color.rgb = _rgb(MUTED_COLOR)

    footer_paragraph.add_run("\t")
    prefix = footer_paragraph.add_run("Página ")
    prefix.font.name = FONT
    prefix.font.size = Pt(7.5)
    prefix.font.color.rgb = _rgb(MUTED_COLOR)
    _add_field(footer_paragraph, "PAGE", size=7.5)
    separator = footer_paragraph.add_run(" de ")
    separator.font.name = FONT
    separator.font.size = Pt(7.5)
    separator.font.color.rgb = _rgb(MUTED_COLOR)
    _add_field(footer_paragraph, "SECTIONPAGES", size=7.5)

    # Reinicia a numeração na primeira página de conteúdo.
    section_pr = section._sectPr
    page_numbering = OxmlElement("w:pgNumType")
    page_numbering.set(qn("w:start"), "1")
    section_pr.append(page_numbering)


def _add_image_block(
    doc,
    step: ManualStep,
    figure_number: int,
    accent: str,
) -> None:
    description = _clean(step.description) or f"Passo {figure_number:02d}"
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _table_width(table, CONTENT_WIDTH_CM)
    cell = table.cell(0, 0)
    cell.width = Cm(CONTENT_WIDTH_CM)
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    _cell_margins(cell, top=90, start=90, bottom=90, end=90)
    _cell_borders(
        cell,
        left={"sz": 4, "color": BORDER_COLOR},
        top={"sz": 4, "color": BORDER_COLOR},
        right={"sz": 4, "color": BORDER_COLOR},
        bottom={"sz": 4, "color": BORDER_COLOR},
    )
    _shade_cell(cell, "#FFFFFF")

    image_paragraph = cell.paragraphs[0]
    image_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    image_paragraph.paragraph_format.space_after = Pt(2)

    image_ok = False
    try:
        width_cm, height_cm = _image_size_cm(step.image_path, 16.2, 16.5)
        run = image_paragraph.add_run()
        run.add_picture(step.image_path, width=Cm(width_cm), height=Cm(height_cm))
        try:
            doc_pr = run._inline.docPr
            doc_pr.set("descr", _short(description, 120))
            doc_pr.set("title", f"Figura {figure_number:02d}")
        except Exception:
            pass
        image_ok = True
    except Exception as exc:
        logger.warning("Imagem do passo %s não pôde ser inserida: %s", figure_number, exc)

    if not image_ok:
        placeholder = image_paragraph.add_run("Imagem não disponível")
        placeholder.font.name = FONT
        placeholder.font.size = Pt(9)
        placeholder.font.italic = True
        placeholder.font.color.rgb = _rgb(MUTED_COLOR)

    caption = cell.add_paragraph(style="Manual Caption")
    caption.add_run(f"Figura {figure_number:02d} — {_short(description, 90)}")
    _row_no_split(table.rows[0])

    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.space_after = Pt(2)
    spacer.add_run("").font.size = Pt(1)


def _add_notes_block(doc, notes: str, accent: str) -> None:
    table = doc.add_table(rows=1, cols=1)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    _table_width(table, CONTENT_WIDTH_CM)
    cell = table.cell(0, 0)
    cell.width = Cm(CONTENT_WIDTH_CM)
    _cell_margins(cell, top=130, start=190, bottom=130, end=170)
    _cell_borders(
        cell,
        left={"sz": 24, "color": accent},
        top=None,
        right=None,
        bottom=None,
    )
    _shade_cell(cell, mix_color(accent, "#FFFFFF", 0.92))

    label_paragraph = cell.paragraphs[0]
    label_paragraph.paragraph_format.space_after = Pt(2)
    label_run = label_paragraph.add_run("OBSERVAÇÕES")
    label_run.font.name = FONT
    label_run.font.size = Pt(7.5)
    label_run.font.bold = True
    label_run.font.color.rgb = _rgb(accent)

    text_paragraph = cell.add_paragraph(style="Manual Note Text")
    _add_multiline(text_paragraph, notes)
    _row_no_split(table.rows[0])


def _add_step(doc, step: ManualStep, index: int, config: ManualConfig, accent: str) -> None:
    label = doc.add_paragraph(style="Manual Step Label")
    if config.page_break_per_step and index > 1:
        label.paragraph_format.page_break_before = True
    label.add_run(f"PASSO {index:02d}")

    title = doc.add_paragraph(style="Manual Step Title")
    title.add_run(_clean(step.description) or f"Passo {index:02d}")

    if config.include_metadata:
        meta = doc.add_paragraph(style="Manual Meta")
        parts: list[str] = []
        if step.captured_at is not None:
            parts.append(
                "Capturado em "
                + step.captured_at.strftime("%d/%m/%Y às %H:%M:%S")
            )
        parts.append(button_label(step.button))
        if step.x is not None and step.y is not None:
            parts.append(f"({step.x}, {step.y})")
        meta.add_run(" · ".join(parts))

    _add_image_block(doc, step, index, accent)

    notes = _clean(step.notes)
    if notes:
        _add_notes_block(doc, notes, accent)


def _set_core_properties(doc, config: ManualConfig) -> None:
    properties = doc.core_properties
    properties.title = _clean(config.title) or "Manual de Procedimentos"
    properties.subject = "Manual de procedimentos"
    properties.author = _clean(config.author) or _clean(config.company) or "Manual Auto"
    properties.last_modified_by = _clean(config.company) or properties.author
    properties.category = "Manual"
    properties.comments = (
        "Documento gerado automaticamente em "
        + config.generated_at.strftime("%d/%m/%Y %H:%M")
        + "."
    )
    properties.language = "pt-BR"
    properties.created = config.generated_at
    properties.modified = config.generated_at


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def build_manual(
    config: ManualConfig,
    steps: Sequence[ManualStep],
) -> bytes:
    """Gera o manual e devolve os bytes do arquivo .docx."""
    steps = list(steps)
    if not steps:
        raise ValueError("Nenhum passo selecionado para exportação.")

    accent = normalize_hex(config.accent_color)
    logo = _prepare_logo(config.logo)
    config = ManualConfig(
        title=_clean(config.title) or "Manual de Procedimentos",
        company=_clean(config.company),
        subtitle=_clean(config.subtitle),
        author=_clean(config.author),
        logo=config.logo,
        accent_color=accent,
        include_metadata=bool(config.include_metadata),
        page_break_per_step=bool(config.page_break_per_step),
        generated_at=config.generated_at,
    )

    doc = Document()
    _configure_styles(doc, accent)
    _configure_section(doc.sections[0])
    _set_core_properties(doc, config)

    _build_cover(doc, config, logo, len(steps))

    content_section = doc.sections[1]
    _configure_section(content_section)
    _build_header_footer(content_section, config, logo, accent)

    heading = doc.add_paragraph(style="Heading 1")
    heading.add_run("Procedimento")
    _paragraph_border(heading, "bottom", accent, size=10, space=3)

    lead = doc.add_paragraph(style="Manual Lead")
    lead.add_run(
        f"Este manual descreve o procedimento em {len(steps)} "
        f"{'passo' if len(steps) == 1 else 'passos'}. "
        "Siga as instruções na ordem apresentada e observe as observações "
        "destacadas em cada etapa. As áreas circuladas em vermelho nas "
        "imagens indicam o local exato de cada clique."
    )

    for index, step in enumerate(steps, start=1):
        _add_step(doc, step, index, config, accent)

    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


def save_manual(
    path: str | Path,
    config: ManualConfig,
    steps: Sequence[ManualStep],
) -> Path:
    """Gera o manual e grava em ``path``. Retorna o caminho final."""
    target = Path(path)
    if target.suffix.lower() != ".docx":
        target = target.with_suffix(".docx")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_manual(config, steps))
    return target
