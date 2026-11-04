"""Build the paper from content.py: IEEEtran LaTeX source and a two-column PDF preview.

    python docs/paper/build_paper.py

The .tex file is what a conference expects (upload it with figures/ to Overleaf).
The PDF is built with ReportLab because no LaTeX compiler is installed here, so
its layout approximates IEEE style; page counts may differ slightly.
"""

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

import content as C

HERE = Path(__file__).parent
FIGURES = HERE / "figures"
ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]
FONT_DIR = Path("C:/Windows/Fonts")


def citation_order():
    order = []
    for block in C.BLOCKS:
        texts = []
        if block[0] == "p":
            texts = [block[1]]
        elif block[0] == "list":
            texts = block[1]
        for text in texts:
            for group in re.findall(r"\{cite:([^}]+)\}", text):
                for key in (k.strip() for k in group.split(",")):
                    if key not in order:
                        order.append(key)
    missing = set(C.REFERENCES) - set(order)
    assert not missing, f"Unused references: {missing}"
    return order


ORDER = citation_order()
NUMBER = {k: i + 1 for i, k in enumerate(ORDER)}


def architecture_figure():
    plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"]})
    fig, ax = plt.subplots(figsize=(3.45, 2.5))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 72)
    ax.axis("off")

    def box(x, y, w, h, title, sub, accent=False):
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0,rounding_size=1.6",
            facecolor="#e4f0ea" if accent else "white",
            edgecolor="#1f6f54" if accent else "#555555", linewidth=1.1 if accent else 0.7,
        ))
        ax.text(x + w / 2, y + h * 0.63, title, ha="center", va="center", fontsize=7.2, fontweight="bold")
        ax.text(x + w / 2, y + h * 0.28, sub, ha="center", va="center", fontsize=6)

    def arrow(a, b, style="-|>", connection=None):
        ax.add_patch(FancyArrowPatch(
            a, b, arrowstyle=style, mutation_scale=6, linewidth=0.7, color="#444444",
            shrinkA=0, shrinkB=0, connectionstyle=connection or "arc3",
        ))

    box(2, 52, 28, 16, "Phone browser", "camera, live display")
    box(36, 52, 28, 16, "YOLO11s detector", "evidence only")
    box(70, 52, 28, 16, "Plant record", "history per plant", accent=True)
    box(70, 28, 28, 16, "Diagnostic engine", "repeat-sighting rule")
    box(36, 28, 28, 16, "Action manager", "one reasoned action")
    box(2, 28, 28, 16, "ESP32 robot", "drive, arm, DHT22")
    box(36, 4, 28, 16, "Operator", "runs and approves")

    arrow((30, 60), (36, 60))
    arrow((64, 60), (70, 60))
    arrow((84, 52), (84, 44), style="<|-|>")
    arrow((70, 36), (64, 36))
    arrow((36, 36), (30, 36))
    arrow((50, 20), (50, 28))
    arrow((16, 44), (16, 52))
    ax.text(14.5, 48, "return visit", fontsize=6, ha="right", va="center")
    ax.text(33, 46.5, "Bluetooth", fontsize=6, ha="center", va="center")
    arrow((33, 45), (33, 37), style="-")
    fig.subplots_adjust(0, 0, 1, 1)
    fig.savefig(FIGURES / "architecture.png", dpi=300)
    plt.close(fig)


# ---------- LaTeX ----------

SYMBOLS = {
    "ρ": r"$\rho$", "τ": r"$\tau$", "≥": r"$\geq$", "×": r"$\times$", "²": r"$^2$",
    "–": "--", "→": r"$\rightarrow$", "·": r"$\cdot$", "−": r"$-$",
}


def tex(text):
    text = text.replace("&amp;", "&")
    parts = re.split(r"(\{cite:[^}]+\}|<i>|</i>)", text)
    out = []
    for part in parts:
        if part.startswith("{cite:"):
            out.append(r"\cite{" + part[6:-1].replace(" ", "") + "}")
        elif part == "<i>":
            out.append(r"\emph{")
        elif part == "</i>":
            out.append("}")
        else:
            part = re.sub(r"([%&_#$])", r"\\\1", part)
            for k, v in SYMBOLS.items():
                part = part.replace(k, v)
            part = part.replace("“", "``").replace("”", "''")
            out.append(part)
    return "".join(out)


def write_latex():
    lines = [
        r"\documentclass[conference]{IEEEtran}",
        r"\usepackage{cite}",
        r"\usepackage{amsmath,amssymb}",
        r"\usepackage{graphicx}",
        r"\usepackage{booktabs}",
        r"\usepackage[T1]{fontenc}",
        r"\usepackage[utf8]{inputenc}",
        r"\begin{document}",
        r"\title{" + tex(C.TITLE) + "}",
        r"\author{\IEEEauthorblockN{" + tex(C.AUTHORS) + r"}\IEEEauthorblockA{" + tex(C.AFFILIATION) + "}}",
        r"\maketitle",
        r"\begin{abstract}" + tex(C.ABSTRACT) + r"\end{abstract}",
        r"\begin{IEEEkeywords}" + tex(C.KEYWORDS) + r"\end{IEEEkeywords}",
    ]
    for block in C.BLOCKS:
        kind = block[0]
        if kind == "h1":
            lines.append(r"\section{" + tex(block[1]) + "}")
        elif kind == "h2":
            lines.append(r"\subsection{" + tex(block[1]) + "}")
        elif kind == "p":
            lines.append(tex(block[1]) + "\n")
        elif kind == "list":
            lines.append(r"\begin{itemize}")
            lines += [r"\item " + tex(item) for item in block[1]]
            lines.append(r"\end{itemize}")
        elif kind == "eq":
            lines += [r"\begin{equation}", block[1], r"\end{equation}"]
        elif kind == "fig":
            lines += [
                r"\begin{figure}[t]", r"\centering",
                r"\includegraphics[width=\columnwidth]{figures/" + block[1] + "}",
                r"\caption{" + tex(block[2]) + "}", r"\end{figure}",
            ]
        elif kind == "table":
            _, caption, header, rows, _ = block
            lines += [
                r"\begin{table}[t]", r"\centering", r"\caption{" + tex(caption) + "}",
                r"\footnotesize", r"\begin{tabular}{" + "l" * len(header) + "}", r"\toprule",
                " & ".join(tex(h) for h in header) + r" \\", r"\midrule",
            ]
            lines += [" & ".join(tex(c) for c in row) + r" \\" for row in rows]
            lines += [r"\bottomrule", r"\end{tabular}", r"\end{table}"]
    lines += [r"\section*{Acknowledgment}", tex(C.ACK), r"\begin{thebibliography}{99}"]
    for key in ORDER:
        lines.append(r"\bibitem{" + key + "} " + tex(C.REFERENCES[key]))
    lines += [r"\end{thebibliography}", r"\end{document}"]
    (HERE / "crap_paper.tex").write_text("\n".join(lines), encoding="utf-8")


# ---------- PDF ----------

def register_fonts():
    for name, file in (("Times", "times.ttf"), ("Times-B", "timesbd.ttf"), ("Times-I", "timesi.ttf"), ("Times-BI", "timesbi.ttf")):
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))
    pdfmetrics.registerFontFamily("Times", normal="Times", bold="Times-B", italic="Times-I", boldItalic="Times-BI")


def pdf_text(text):
    def cite(match):
        numbers = sorted(NUMBER[k.strip()] for k in match.group(1).split(","))
        return "[" + ", ".join(str(n) for n in numbers) + "]"

    text = re.sub(r"\{cite:([^}]+)\}", cite, text)
    text = re.sub(r"(?<![\w.:/-])-(?=\d)", "−", text)
    return re.sub(r"&(?!amp;|lt;|gt;)", "&amp;", text)


def equation_image(latex, number):
    fig = plt.figure(figsize=(3.0, 0.32))
    expr = latex.replace(r"\quad", r"\;\;").replace(r"\text{and}", r"\mathrm{and}")
    expr = re.sub(r"\\text\{([^}]*)\}", lambda m: r"\mathrm{" + m.group(1).replace(" ", r"\ ") + "}", expr)
    plt.rcParams["mathtext.fontset"] = "stix"
    fig.text(0.5, 0.5, f"${expr}$", ha="center", va="center", fontsize=9.5)
    path = FIGURES / f"equation_{number}.png"
    fig.savefig(path, dpi=300)
    plt.close(fig)
    return path


def write_pdf():
    register_fonts()
    body = ParagraphStyle("body", fontName="Times", fontSize=10, leading=11.6, alignment=TA_JUSTIFY, firstLineIndent=10, spaceAfter=3)
    h1 = ParagraphStyle("h1", fontName="Times", fontSize=10, leading=12, alignment=TA_CENTER, spaceBefore=8, spaceAfter=4, keepWithNext=1)
    h2 = ParagraphStyle("h2", fontName="Times-I", fontSize=10, leading=12, spaceBefore=5, spaceAfter=3, keepWithNext=1)
    item = ParagraphStyle("item", parent=body, firstLineIndent=0, leftIndent=12, bulletIndent=2, spaceAfter=2, bulletFontName="Times", bulletFontSize=10)
    title = ParagraphStyle("title", fontName="Times", fontSize=22, leading=25, alignment=TA_CENTER, spaceAfter=10)
    author = ParagraphStyle("author", fontName="Times", fontSize=11, leading=13, alignment=TA_CENTER)
    affil = ParagraphStyle("affil", fontName="Times-I", fontSize=10, leading=12, alignment=TA_CENTER)
    abstract = ParagraphStyle("abstract", fontName="Times-B", fontSize=9, leading=10.4, alignment=TA_JUSTIFY, spaceAfter=4)
    caption = ParagraphStyle("caption", fontName="Times", fontSize=8, leading=9.4, alignment=TA_JUSTIFY, spaceBefore=3, spaceAfter=8)
    tcaption = ParagraphStyle("tcaption", fontName="Times", fontSize=8, leading=9.6, alignment=TA_CENTER, spaceBefore=6, spaceAfter=3)
    cell = ParagraphStyle("cell", fontName="Times", fontSize=8, leading=9.2)
    cellb = ParagraphStyle("cellb", fontName="Times-B", fontSize=8, leading=9.2)
    ref = ParagraphStyle("ref", fontName="Times", fontSize=8, leading=9.3, alignment=TA_JUSTIFY, leftIndent=16, firstLineIndent=-16, spaceAfter=2)

    W, H = letter
    margin, gap = 0.625 * inch, 0.25 * inch
    col = (W - 2 * margin - gap) / 2
    top, bottom = 0.75 * inch, 0.9 * inch
    title_h = 1.62 * inch
    first_h = H - top - bottom - title_h

    doc = BaseDocTemplate(str(HERE / "crap_paper.pdf"), pagesize=letter, title=C.TITLE, author="C.R.A.P team")

    def page_number(canvas, d):
        canvas.setFont("Times", 8)
        canvas.drawCentredString(W / 2, 0.5 * inch, str(d.page))

    doc.addPageTemplates([
        PageTemplate(id="first", onPage=page_number, frames=[
            Frame(margin, H - top - title_h, W - 2 * margin, title_h, 0, 0, 0, 0, id="title"),
            Frame(margin, bottom, col, first_h, 0, 0, 0, 0, id="c1"),
            Frame(margin + col + gap, bottom, col, first_h, 0, 0, 0, 0, id="c2"),
        ]),
        PageTemplate(id="rest", onPage=page_number, frames=[
            Frame(margin, bottom, col, H - top - bottom, 0, 0, 0, 0, id="r1"),
            Frame(margin + col + gap, bottom, col, H - top - bottom, 0, 0, 0, 0, id="r2"),
        ]),
    ])

    story = [
        Paragraph(C.TITLE, title), Paragraph(C.AUTHORS, author), Paragraph(C.AFFILIATION, affil),
        NextPageTemplate("rest"), FrameBreak(),
        Paragraph("<i>Abstract</i>—" + pdf_text(C.ABSTRACT), abstract),
        Paragraph("<i>Index Terms</i>—" + pdf_text(C.KEYWORDS), abstract),
    ]

    section = sub = fig_no = table_no = eq_no = 0
    for block in C.BLOCKS:
        kind = block[0]
        if kind == "h1":
            section, sub = section + 1, 0
            story.append(Paragraph(f"{ROMAN[section - 1]}. {block[1].upper()}", h1))
        elif kind == "h2":
            sub += 1
            story.append(Paragraph(f"{chr(64 + sub)}. {block[1]}", h2))
        elif kind == "p":
            story.append(Paragraph(pdf_text(block[1]), body))
        elif kind == "list":
            story += [Paragraph(pdf_text(t), item, bulletText="•") for t in block[1]]
        elif kind == "eq":
            eq_no += 1
            path = equation_image(block[1], eq_no)
            row = Table(
                [[Image(str(path), width=3.0 * inch, height=0.32 * inch), Paragraph(f"({eq_no})", cell)]],
                colWidths=[col - 0.3 * inch, 0.3 * inch],
            )
            row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
            story.append(row)
        elif kind == "fig":
            fig_no += 1
            _, file, text, width = block
            from PIL import Image as PILImage

            with PILImage.open(FIGURES / file) as im:
                ratio = im.height / im.width
            story.append(KeepTogether([
                Image(str(FIGURES / file), width=width * inch, height=width * inch * ratio),
                Paragraph(f"Fig. {fig_no}. {pdf_text(text)}", caption),
            ]))
        elif kind == "table":
            table_no += 1
            _, text, header, rows, widths = block
            data = [[Paragraph(h, cellb) for h in header]] + [[Paragraph(c, cell) for c in r] for r in rows]
            table = Table(data, colWidths=[w * inch for w in widths])
            table.setStyle(TableStyle([
                ("LINEABOVE", (0, 0), (-1, 0), 0.7, colors.black),
                ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.black),
                ("LINEBELOW", (0, -1), (-1, -1), 0.7, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]))
            story.append(KeepTogether([
                Paragraph(f"TABLE {ROMAN[table_no - 1]}<br/>{pdf_text(text).upper()}", tcaption),
                table, Spacer(1, 6),
            ]))

    story.append(Paragraph("ACKNOWLEDGMENT", h1))
    story.append(Paragraph(C.ACK, body))
    story.append(Paragraph("REFERENCES", h1))
    for key in ORDER:
        story.append(Paragraph(f"[{NUMBER[key]}]&nbsp;&nbsp;{pdf_text(C.REFERENCES[key])}", ref))
    doc.build(story)
    return doc.page


if __name__ == "__main__":
    architecture_figure()
    write_latex()
    pages = write_pdf()
    print("pages", pages, "references", len(ORDER))
