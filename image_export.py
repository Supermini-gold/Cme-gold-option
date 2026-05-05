import io
import os
import re
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')

def strip_emoji(text):
    """Remove emoji characters for cleaner rendering"""
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF"
        "\U00002600-\U000026FF\U00002B50-\U00002B55\U0001FA00-\U0001FA6F]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub('', text)

def clean_markdown(text):
    """Convert markdown to clean text for image"""
    text = strip_emoji(text)
    text = re.sub(r'\*\*\*(.*?)\*\*\*', r'\1', text)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`(.*?)`', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def wrap_text_pillow(draw, text, font, max_width):
    """Wrap text to fit within max_width, supporting Thai characters"""
    lines = []
    current_line = ""
    for char in text:
        if char == '\n':
            lines.append(current_line)
            current_line = ""
            continue
            
        is_combining = ('\u0E31' <= char <= '\u0E3A') or ('\u0E47' <= char <= '\u0E4E')
        if not is_combining and current_line:
            # Check width
            if draw.textlength(current_line + char, font=font) > max_width:
                lines.append(current_line)
                current_line = char
            else:
                current_line += char
        else:
            current_line += char
            
    if current_line:
        lines.append(current_line)
    return lines

# Section header keywords to detect
SECTION_KEYWORDS = [
    'Snapshot', 'Expected Range', 'Key Levels', 'Z-Score',
    'Volume', 'Heatmap', 'Volatility', 'Greeks',
    'Anomaly', 'Bias', 'CFD', 'Long', 'Short', 'Hedging',
    'สรุป', 'แนะนำ', 'สัญญาณ', 'กลยุทธ์'
]

def is_section_header(line):
    stripped = line.strip()
    if not stripped:
        return False
    for kw in SECTION_KEYWORDS:
        if kw in stripped and len(stripped) < 80:
            return True
    return False

def generate_image(result_text, timestamp=None):
    """Generate a premium PNG report from analysis result text.
    Returns bytes of the PNG file."""
    if timestamp is None:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Load fonts
    font_path_reg = os.path.join(FONT_DIR, 'Sarabun-Regular.ttf')
    font_path_bold = os.path.join(FONT_DIR, 'Sarabun-Bold.ttf')
    
    font_title = ImageFont.truetype(font_path_bold, 36)
    font_subtitle = ImageFont.truetype(font_path_reg, 18)
    font_header = ImageFont.truetype(font_path_bold, 24)
    font_body = ImageFont.truetype(font_path_reg, 22)
    font_table = ImageFont.truetype(font_path_reg, 18)
    font_table_bold = ImageFont.truetype(font_path_bold, 18)
    
    # Configuration
    IMG_WIDTH = 800
    MARGIN_X = 40
    MARGIN_Y = 40
    MAX_TEXT_WIDTH = IMG_WIDTH - (MARGIN_X * 2)
    
    # Colors
    BG_COLOR = (25, 25, 30)
    GOLD_COLOR = (212, 175, 55)
    TEXT_MAIN = (230, 230, 235)
    TEXT_DIM = (160, 160, 170)
    LINE_COLOR = (60, 60, 70)
    TABLE_HEADER_BG = (45, 45, 55)
    TABLE_ROW_BG = (32, 32, 38)
    TABLE_ALT_BG = (28, 28, 33)
    
    cleaned = clean_markdown(result_text)
    lines = cleaned.split('\n')
    
    # --- FIRST PASS: Calculate required height & Parse structure ---
    dummy_img = Image.new('RGB', (1, 1))
    draw_measure = ImageDraw.Draw(dummy_img)
    
    current_y = MARGIN_Y
    current_y += 60 # Title + subtitle space
    current_y += 40 # Date space
    
    parsed_blocks = []
    in_table = False
    table_row_count = 0
    
    for line in lines:
        line = line.rstrip()
        if not line:
            if in_table:
                in_table = False
                table_row_count = 0
            current_y += 10
            continue
            
        if '|' in line and line.strip().startswith('|'):
            cells = [c.strip() for c in line.split('|') if c.strip()]
            # Skip separator rows (|---|---|)
            if cells and all(c.replace('-', '').replace(':', '').strip() == '' for c in cells):
                continue
            if cells:
                is_header = not in_table # First row of a table block is header
                in_table = True
                parsed_blocks.append(('table_row', (cells, is_header, table_row_count)))
                table_row_count += 1
                current_y += 38
            continue
        
        in_table = False
        table_row_count = 0
            
        if is_section_header(line):
            parsed_blocks.append(('header', line.strip()))
            current_y += 55
            continue
            
        if line.strip().startswith(('-', '•')):
            wrapped = wrap_text_pillow(draw_measure, line.strip(), font_body, MAX_TEXT_WIDTH - 30)
            parsed_blocks.append(('bullet', wrapped))
            current_y += len(wrapped) * 32 + 10
            continue
            
        # Regular text
        wrapped = wrap_text_pillow(draw_measure, line, font_body, MAX_TEXT_WIDTH)
        parsed_blocks.append(('text', wrapped))
        current_y += len(wrapped) * 32 + 10
        
    current_y += 60 # Footer space
    
    # --- SECOND PASS: Draw elements ---
    img = Image.new('RGB', (IMG_WIDTH, current_y), color=BG_COLOR)
    draw = ImageDraw.Draw(img)
    
    # Subtle gradient background for header (optional, but keep it simple for now)
    # y = 0
    # for i in range(150):
    #     alpha = int(25 * (1 - i/150))
    #     draw.line([(0, i), (IMG_WIDTH, i)], fill=(25+alpha, 25+alpha, 30+alpha))

    y = MARGIN_Y
    
    # Title
    draw.text((IMG_WIDTH//2, y), 'Gold Options Analysis Report', font=font_title, fill=GOLD_COLOR, anchor='mt')
    y += 45
    draw.text((IMG_WIDTH//2, y), 'CME QuikStrike  |  Institutional Grade Analysis', font=font_subtitle, fill=TEXT_DIM, anchor='mt')
    y += 35
    
    # Line
    draw.line([(MARGIN_X, y), (IMG_WIDTH - MARGIN_X, y)], fill=LINE_COLOR, width=2)
    y += 15
    
    # Date
    draw.text((IMG_WIDTH - MARGIN_X, y), f'Analysis Date: {timestamp}', font=font_subtitle, fill=TEXT_DIM, anchor='rm')
    y += 25
    
    for block_type, data in parsed_blocks:
        if block_type == 'header':
            y += 15
            # Gold rect
            draw.rectangle([(MARGIN_X, y), (MARGIN_X + 6, y + 26)], fill=GOLD_COLOR)
            draw.text((MARGIN_X + 20, y + 13), data, font=font_header, fill=(255,255,255), anchor='lm')
            y += 40
            draw.line([(MARGIN_X, y), (IMG_WIDTH - MARGIN_X, y)], fill=LINE_COLOR, width=1)
            y += 15
            
        elif block_type == 'text':
            for l in data:
                draw.text((MARGIN_X, y), l, font=font_body, fill=TEXT_MAIN)
                y += 32
            y += 10
            
        elif block_type == 'bullet':
            for i, l in enumerate(data):
                x_pos = MARGIN_X + 25 if i == 0 else MARGIN_X + 45
                if i == 0:
                    dot_y = y + 14
                    draw.ellipse([(MARGIN_X + 5, dot_y), (MARGIN_X + 11, dot_y + 6)], fill=GOLD_COLOR)
                    
                text_to_draw = l[2:] if i == 0 and (l.startswith('- ') or l.startswith('• ')) else l
                draw.text((x_pos, y), text_to_draw, font=font_body, fill=TEXT_MAIN)
                y += 32
            y += 10
            
        elif block_type == 'table_row':
            cells, is_header, row_idx = data
            num_cols = max(len(cells), 1)
            col_w = MAX_TEXT_WIDTH / num_cols
            x = MARGIN_X
            
            row_bg = TABLE_HEADER_BG if is_header else (TABLE_ALT_BG if row_idx % 2 == 1 else TABLE_ROW_BG)
            draw.rectangle([(x, y), (x + MAX_TEXT_WIDTH, y + 38)], fill=row_bg, outline=LINE_COLOR)
            
            fnt = font_table_bold if is_header else font_table
            txt_fill = GOLD_COLOR if is_header else TEXT_MAIN
            
            for cell_text in cells:
                # Basic clipping for table cells
                clipped = cell_text[:40]
                draw.text((x + col_w//2, y + 19), clipped, font=fnt, fill=txt_fill, anchor='mm')
                if not is_header:
                    draw.line([(x, y), (x, y + 38)], fill=LINE_COLOR, width=1)
                x += col_w
            y += 38
            
    # Footer
    y += 20
    draw.line([(MARGIN_X, y), (IMG_WIDTH - MARGIN_X, y)], fill=GOLD_COLOR, width=1)
    y += 20
    draw.text((IMG_WIDTH//2, y), 'Generated by Gold Options Bot  |  For informational purposes only. Not financial advice.', font=font_table, fill=TEXT_DIM, anchor='mm')
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()
