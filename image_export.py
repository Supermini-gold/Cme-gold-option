import io
import os
import re
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')

# ─── Emoji / Markdown Cleanup ──────────────────────────────────────────────────

def strip_emoji(text):
    """Remove emoji/symbol unicode blocks that Sarabun font cannot render"""
    emoji_pattern = re.compile(
        "["
        "\U0001F000-\U0001F9FF"  # Miscellaneous Symbols and Pictographs, Emoticons, etc.
        "\U0001FA00-\U0001FAFF"  # Symbols and Pictographs Extended-A
        "\U00002600-\U000026FF"  # Miscellaneous Symbols
        "\U00002700-\U000027BF"  # Dingbats
        "\U0001F1E0-\U0001F1FF"  # Flags
        "\uFE00-\uFE0F"          # Variation Selectors
        "\u2000-\u2BFF"          # Arrows, symbols, etc.
        "]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub('', text)


def clean_markdown(text):
    """Strip markdown syntax to plain text for PIL rendering"""
    text = strip_emoji(text)
    text = re.sub(r'\*\*\*(.*?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.*?)\*\*',     r'\1', text)
    text = re.sub(r'\*(.*?)\*',          r'\1', text)
    text = re.sub(r'```[\s\S]*?```',     '',    text)
    text = re.sub(r'`(.*?)`',            r'\1', text)
    text = re.sub(r'^#{1,6}\s+',         '',    text, flags=re.MULTILINE)
    text = re.sub(r'^---+$',             '',    text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}',             '\n\n', text)
    return text.strip()


# ─── Text Wrapping ─────────────────────────────────────────────────────────────

def wrap_text_pillow(draw, text, font, max_width):
    """Wrap text to fit within max_width, Thai-aware (never crashes on tiny width)"""
    if max_width < 10:
        return [text[:20]]  # Safety: return truncated text if space is too small

    lines = []
    current_line = ""
    for char in text:
        if char == '\n':
            lines.append(current_line)
            current_line = ""
            continue

        # Thai combining/tone marks should not start a new line
        is_combining = ('\u0E31' <= char <= '\u0E3A') or ('\u0E47' <= char <= '\u0E4E')
        if not is_combining and current_line:
            try:
                w = draw.textlength(current_line + char, font=font)
            except Exception:
                w = 0
            if w > max_width:
                lines.append(current_line)
                current_line = char
            else:
                current_line += char
        else:
            current_line += char

    if current_line:
        lines.append(current_line)
    return lines if lines else [""]


def safe_text_length(draw, text, font):
    """Get text length safely, return 0 on any error"""
    try:
        return draw.textlength(text, font=font)
    except Exception:
        return 0


def clip_text_to_width(draw, text, font, max_w):
    """Clip text with '…' so it always fits within max_w pixels"""
    if max_w < 5:
        return ""
    try:
        if draw.textlength(text, font=font) <= max_w:
            return text
        # Binary search for the right length
        lo, hi = 0, len(text)
        ellipsis = "..."
        ew = draw.textlength(ellipsis, font=font)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if draw.textlength(text[:mid], font=font) + ew <= max_w:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + ellipsis if lo < len(text) else text
    except Exception:
        return text[:15]


# ─── Section Header Detection ──────────────────────────────────────────────────

SECTION_KEYWORDS = [
    'Snapshot', 'Expected Range', 'Expected Move', 'Key Levels', 'Z-Score',
    'Volume', 'Heatmap', 'Volatility', 'Greeks', 'Anomaly', 'Bias', 'CFD',
    'Long', 'Short', 'Hedging', 'สรุป', 'แนะนำ', 'สัญญาณ', 'กลยุทธ์',
    'Scorecard', 'Signal', 'Strike Clustering', 'Session Momentum',
    'Whale', 'Regime', 'Macro', 'Trading Plan'
]


def is_section_header(line):
    stripped = line.strip()
    if not stripped or len(stripped) > 100:
        return False
    for kw in SECTION_KEYWORDS:
        if kw in stripped:
            return True
    return False


# ─── Table Column Width Calculation ───────────────────────────────────────────

MIN_COL_W = 60  # Minimum column width in pixels


def compute_col_widths(all_rows_cells, draw, font, total_width):
    """
    Calculate adaptive column widths.
    - Tries to fit content; falls back to equal widths with MIN_COL_W floor.
    - Returns a list of pixel widths for each column.
    """
    if not all_rows_cells:
        return []

    num_cols = max(len(row) for row in all_rows_cells)
    if num_cols == 0:
        return []

    # Calculate the natural max text width for each column
    natural = [MIN_COL_W] * num_cols
    for row in all_rows_cells:
        for ci, cell in enumerate(row):
            w = safe_text_length(draw, cell, font) + 16  # 8px padding each side
            if w > natural[ci]:
                natural[ci] = w

    total_natural = sum(natural)
    if total_natural <= total_width:
        # Scale up proportionally to fill
        scale = total_width / total_natural
        return [int(n * scale) for n in natural]
    else:
        # Scale down, but never below MIN_COL_W
        # First, identify columns that can shrink
        scale = total_width / total_natural
        widths = [max(MIN_COL_W, int(n * scale)) for n in natural]
        # Adjust last column to consume remaining space
        widths[-1] = max(MIN_COL_W, total_width - sum(widths[:-1]))
        return widths


# ─── Main Image Generator ──────────────────────────────────────────────────────

def generate_image(result_text, timestamp=None):
    """
    Generate a premium PNG report from analysis result text.
    Returns bytes of the PNG file.
    Robust against wide/narrow tables and long Thai text.
    """
    if timestamp is None:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # ── Load fonts ──
    font_path_reg  = os.path.join(FONT_DIR, 'Sarabun-Regular.ttf')
    font_path_bold = os.path.join(FONT_DIR, 'Sarabun-Bold.ttf')

    font_title       = ImageFont.truetype(font_path_bold, 34)
    font_subtitle    = ImageFont.truetype(font_path_reg,  17)
    font_header      = ImageFont.truetype(font_path_bold, 22)
    font_body        = ImageFont.truetype(font_path_reg,  20)
    font_table       = ImageFont.truetype(font_path_reg,  16)
    font_table_bold  = ImageFont.truetype(font_path_bold, 16)

    # ── Layout constants ──
    IMG_WIDTH    = 900
    MARGIN_X     = 36
    MARGIN_Y     = 40
    MAX_TEXT_W   = IMG_WIDTH - MARGIN_X * 2   # 828 px
    ROW_H        = 34                          # Table row height
    LINE_SPACING = 28                          # Body text line height

    # ── Colors ──
    BG_COLOR        = (22, 22, 28)
    GOLD_COLOR      = (212, 175, 55)
    TEXT_MAIN       = (228, 228, 235)
    TEXT_DIM        = (155, 155, 168)
    LINE_COLOR      = (55, 55, 68)
    TABLE_HDR_BG    = (42, 42, 55)
    TABLE_ROW_BG    = (30, 30, 38)
    TABLE_ALT_BG    = (26, 26, 34)

    cleaned = clean_markdown(result_text)
    raw_lines = cleaned.split('\n')

    # ══════════════════════════════════════════════════════════
    # PASS 0 — Parse raw lines → typed blocks
    # Each block: ('type', data)
    # Types: header | text | bullet | table_group
    # table_group data: list of (cells_list, is_header_row, row_idx)
    # ══════════════════════════════════════════════════════════
    blocks = []
    in_table = False
    table_rows = []   # accumulates rows for current table

    def flush_table():
        nonlocal in_table, table_rows
        if table_rows:
            blocks.append(('table_group', table_rows))
        table_rows = []
        in_table = False

    for raw in raw_lines:
        line = raw.rstrip()

        # ── Empty line ──
        if not line:
            flush_table()
            blocks.append(('gap', None))
            continue

        # ── Table row ──
        if '|' in line and line.strip().startswith('|'):
            cells = [c.strip() for c in line.split('|')]
            cells = [c for c in cells if c != '']  # drop empty border cells
            # Skip separator rows like |---|---|
            if cells and all(re.match(r'^[-: ]+$', c) for c in cells):
                continue
            if cells:
                is_hdr = not in_table
                row_idx = len(table_rows)
                table_rows.append((cells, is_hdr, row_idx))
                in_table = True
            continue

        # ── Non-table line: flush any pending table first ──
        flush_table()

        # ── Section header ──
        if is_section_header(line):
            blocks.append(('header', line.strip()))
            continue

        # ── Bullet ──
        if line.strip().startswith(('-', '•', '*')):
            blocks.append(('bullet', line.strip()))
            continue

        # ── Regular text ──
        blocks.append(('text', line))

    flush_table()

    # ══════════════════════════════════════════════════════════
    # PASS 1 — Measure heights using a dummy 1×1 draw surface
    # ══════════════════════════════════════════════════════════
    dummy = Image.new('RGB', (1, 1))
    dm    = ImageDraw.Draw(dummy)

    def measure_block(block_type, data):
        """Return pixel height this block will consume"""
        if block_type == 'gap':
            return 8
        if block_type == 'header':
            return 60  # 15 top pad + label + 15 bottom + divider
        if block_type == 'text':
            wrapped = wrap_text_pillow(dm, data, font_body, MAX_TEXT_W)
            return len(wrapped) * LINE_SPACING + 8
        if block_type == 'bullet':
            wrapped = wrap_text_pillow(dm, data.lstrip('-•* '), font_body, MAX_TEXT_W - 30)
            return len(wrapped) * LINE_SPACING + 8
        if block_type == 'table_group':
            # data is list of (cells, is_hdr, row_idx)
            return len(data) * ROW_H + 6
        return 0

    total_h = MARGIN_Y + 60 + 40 + 20  # title + subtitle + date row
    for btype, bdata in blocks:
        total_h += measure_block(btype, bdata)
    total_h += 60  # footer

    # ══════════════════════════════════════════════════════════
    # PASS 2 — Draw everything
    # ══════════════════════════════════════════════════════════
    img  = Image.new('RGB', (IMG_WIDTH, max(total_h, 300)), color=BG_COLOR)
    draw = ImageDraw.Draw(img)

    y = MARGIN_Y

    # ── Title bar ──
    draw.text((IMG_WIDTH // 2, y), 'Gold Options Analysis Report',
              font=font_title, fill=GOLD_COLOR, anchor='mt')
    y += 42
    draw.text((IMG_WIDTH // 2, y),
              'CME QuikStrike  |  Institutional Grade Analysis',
              font=font_subtitle, fill=TEXT_DIM, anchor='mt')
    y += 28
    draw.line([(MARGIN_X, y), (IMG_WIDTH - MARGIN_X, y)], fill=LINE_COLOR, width=2)
    y += 12
    draw.text((IMG_WIDTH - MARGIN_X, y), f'Analysis Date: {timestamp}',
              font=font_subtitle, fill=TEXT_DIM, anchor='rm')
    y += 20

    # ── Content blocks ──
    for btype, bdata in blocks:

        # Gap
        if btype == 'gap':
            y += 8

        # Section header
        elif btype == 'header':
            y += 15
            draw.rectangle([(MARGIN_X, y), (MARGIN_X + 5, y + 24)], fill=GOLD_COLOR)
            draw.text((MARGIN_X + 18, y + 12), bdata,
                      font=font_header, fill=(255, 255, 255), anchor='lm')
            y += 38
            draw.line([(MARGIN_X, y), (IMG_WIDTH - MARGIN_X, y)], fill=LINE_COLOR, width=1)
            y += 12

        # Regular text
        elif btype == 'text':
            for wl in wrap_text_pillow(draw, bdata, font_body, MAX_TEXT_W):
                draw.text((MARGIN_X, y), wl, font=font_body, fill=TEXT_MAIN)
                y += LINE_SPACING
            y += 8

        # Bullet
        elif btype == 'bullet':
            content = bdata.lstrip('-•* ')
            wrapped = wrap_text_pillow(draw, content, font_body, MAX_TEXT_W - 30)
            for i, wl in enumerate(wrapped):
                x_pos = MARGIN_X + 22 if i == 0 else MARGIN_X + 36
                if i == 0:
                    dot_y = y + LINE_SPACING // 2 - 3
                    draw.ellipse([(MARGIN_X + 4, dot_y), (MARGIN_X + 10, dot_y + 6)],
                                 fill=GOLD_COLOR)
                draw.text((x_pos, y), wl, font=font_body, fill=TEXT_MAIN)
                y += LINE_SPACING
            y += 8

        # Table group
        elif btype == 'table_group':
            rows_data = bdata  # list of (cells, is_hdr, row_idx)
            all_cells = [r[0] for r in rows_data]

            # Compute adaptive column widths
            col_widths = compute_col_widths(all_cells, draw, font_table, MAX_TEXT_W)
            if not col_widths:
                continue

            y += 4
            for cells, is_hdr, row_idx in rows_data:
                # Row background
                bg = TABLE_HDR_BG if is_hdr else (TABLE_ALT_BG if row_idx % 2 == 1 else TABLE_ROW_BG)
                draw.rectangle(
                    [(MARGIN_X, y), (MARGIN_X + sum(col_widths), y + ROW_H)],
                    fill=bg, outline=LINE_COLOR
                )

                fnt      = font_table_bold if is_hdr else font_table
                txt_fill = GOLD_COLOR if is_hdr else TEXT_MAIN

                cx = MARGIN_X
                for ci, cw in enumerate(col_widths):
                    cell_text = cells[ci] if ci < len(cells) else ''
                    # Safe clip to column width minus padding
                    cell_text = clip_text_to_width(draw, cell_text, fnt, cw - 8)
                    # Draw cell text left-aligned with 6px padding
                    draw.text((cx + 6, y + ROW_H // 2), cell_text,
                              font=fnt, fill=txt_fill, anchor='lm')
                    # Column divider
                    if ci < len(col_widths) - 1:
                        draw.line([(cx + cw, y), (cx + cw, y + ROW_H)],
                                  fill=LINE_COLOR, width=1)
                    cx += cw

                y += ROW_H
            y += 6

    # ── Footer ──
    y += 16
    draw.line([(MARGIN_X, y), (IMG_WIDTH - MARGIN_X, y)], fill=GOLD_COLOR, width=1)
    y += 18
    draw.text(
        (IMG_WIDTH // 2, y),
        'Generated by Gold Options Bot  |  For informational purposes only. Not financial advice.',
        font=font_table, fill=TEXT_DIM, anchor='mm'
    )

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    return buf.getvalue()
