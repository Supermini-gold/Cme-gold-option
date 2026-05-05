import io
import os
import re
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')

def strip_emoji(text):
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0001F900-\U0001F9FF"
        "\U00002600-\U000026FF\U00002B50-\U00002B55\U0001FA00-\U0001FA6F]+",
        flags=re.UNICODE
    )
    return emoji_pattern.sub('', text)

def clean_markdown(text):
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

def generate_image(result_text, timestamp=None):
    if timestamp is None:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    # Load fonts
    font_path_reg = os.path.join(FONT_DIR, 'Sarabun-Regular.ttf')
    font_path_bold = os.path.join(FONT_DIR, 'Sarabun-Bold.ttf')
    
    font_title = ImageFont.truetype(font_path_bold, 36)
    font_subtitle = ImageFont.truetype(font_path_reg, 18)
    font_header = ImageFont.truetype(font_path_bold, 24)
    font_body = ImageFont.truetype(font_path_reg, 20)
    font_table = ImageFont.truetype(font_path_reg, 16)
    
    # Configuration
    IMG_WIDTH = 800
    MARGIN_X = 40
    MARGIN_Y = 40
    MAX_TEXT_WIDTH = IMG_WIDTH - (MARGIN_X * 2)
    
    # Colors
    BG_COLOR = (25, 25, 30)
    GOLD_COLOR = (212, 175, 55)
    TEXT_MAIN = (220, 220, 225)
    TEXT_DIM = (160, 160, 170)
    LINE_COLOR = (60, 60, 70)
    TABLE_BG = (35, 35, 42)
    
    cleaned = clean_markdown(result_text)
    lines = cleaned.split('\n')
    
    # First pass: calculate required height
    # We use a dummy image/draw for measurement
    dummy_img = Image.new('RGB', (1, 1))
    draw_measure = ImageDraw.Draw(dummy_img)
    
    current_y = MARGIN_Y
    
    # Header area
    current_y += 60 # Title + subtitle space
    current_y += 30 # Date space
    
    SECTION_KEYWORDS = [
        'Snapshot', 'Expected Range', 'Key Levels', 'Z-Score',
        'Volume', 'Heatmap', 'Volatility', 'Greeks',
        'Anomaly', 'Bias', 'CFD', 'Long', 'Short', 'Hedging',
        'สรุป', 'แนะนำ', 'สัญญาณ', 'กลยุทธ์'
    ]
    
    def is_section_header(l):
        stripped = l.strip()
        if not stripped: return False
        for kw in SECTION_KEYWORDS:
            if kw in stripped and len(stripped) < 80: return True
        return False

    parsed_blocks = [] # store elements to draw later
    
    for line in lines:
        line = line.rstrip()
        if not line:
            current_y += 10
            continue
            
        if '|' in line and line.strip().startswith('|'):
            cells = [c.strip() for c in line.split('|') if c.strip()]
            if cells and all(c.replace('-', '').replace(':', '').strip() == '' for c in cells):
                continue
            if cells:
                parsed_blocks.append(('table_row', cells))
                current_y += 25
            continue
            
        if is_section_header(line):
            parsed_blocks.append(('header', line.strip()))
            current_y += 40
            continue
            
        if line.strip().startswith(('-', '•')):
            # Bullet point
            wrapped = wrap_text_pillow(draw_measure, line.strip(), font_body, MAX_TEXT_WIDTH - 30)
            parsed_blocks.append(('bullet', wrapped))
            current_y += len(wrapped) * 30 + 10
            continue
            
        # Regular text
        wrapped = wrap_text_pillow(draw_measure, line, font_body, MAX_TEXT_WIDTH)
        parsed_blocks.append(('text', wrapped))
        current_y += len(wrapped) * 30 + 10
        
    current_y += MARGIN_Y + 40 # Footer space
    
    # Second pass: Draw everything
    img = Image.new('RGB', (IMG_WIDTH, current_y), color=BG_COLOR)
    draw = ImageDraw.Draw(img)
    
    y = MARGIN_Y
    
    # Title
    draw.text((IMG_WIDTH//2, y), 'Gold Options Analysis Report', font=font_title, fill=GOLD_COLOR, anchor='mm')
    y += 35
    draw.text((IMG_WIDTH//2, y), 'CME QuikStrike  |  Institutional Grade Analysis', font=font_subtitle, fill=TEXT_DIM, anchor='mm')
    y += 25
    
    # Line
    draw.line([(MARGIN_X, y), (IMG_WIDTH - MARGIN_X, y)], fill=LINE_COLOR, width=2)
    y += 15
    
    # Date
    draw.text((IMG_WIDTH - MARGIN_X, y), f'Analysis Date: {timestamp}', font=font_subtitle, fill=TEXT_DIM, anchor='rm')
    y += 25
    
    for block_type, data in parsed_blocks:
        if block_type == 'header':
            y += 10
            # Gold rect
            draw.rectangle([(MARGIN_X, y), (MARGIN_X + 6, y + 24)], fill=GOLD_COLOR)
            draw.text((MARGIN_X + 20, y + 12), data, font=font_header, fill=(255,255,255), anchor='lm')
            y += 35
            draw.line([(MARGIN_X, y), (IMG_WIDTH - MARGIN_X, y)], fill=LINE_COLOR, width=1)
            y += 15
            
        elif block_type == 'text':
            for l in data:
                draw.text((MARGIN_X, y), l, font=font_body, fill=TEXT_MAIN)
                y += 30
            y += 10
            
        elif block_type == 'bullet':
            for i, l in enumerate(data):
                x_pos = MARGIN_X + 20 if i == 0 else MARGIN_X + 35
                draw.text((x_pos, y), l, font=font_body, fill=TEXT_MAIN)
                y += 30
            y += 10
            
        elif block_type == 'table_row':
            num_cols = max(len(data), 1)
            col_w = MAX_TEXT_WIDTH / num_cols
            x = MARGIN_X
            
            draw.rectangle([(x, y), (x + MAX_TEXT_WIDTH, y + 24)], fill=TABLE_BG, outline=LINE_COLOR)
            for cell_text in data:
                # clip cell text
                clipped = cell_text[:40]
                draw.text((x + col_w//2, y + 12), clipped, font=font_table, fill=TEXT_MAIN, anchor='mm')
                draw.line([(x, y), (x, y + 24)], fill=LINE_COLOR, width=1)
                x += col_w
            y += 25
            
    # Footer
    draw.line([(MARGIN_X, y), (IMG_WIDTH - MARGIN_X, y)], fill=GOLD_COLOR, width=1)
    y += 15
    draw.text((IMG_WIDTH//2, y), 'Generated by Gold Options Bot  |  For informational purposes only. Not financial advice.', font=font_table, fill=TEXT_DIM, anchor='mm')
    
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()

if __name__ == '__main__':
    text = '''**Gold Options Analysis**

สรุป Bias
[Bullish] ตลาดมีแนวโน้มปรับตัวขึ้น

Volume & Open Interest
- มีปริมาณการซื้อขายที่ระดับ 2300 มากผิดปกติ
- OI เพิ่มขึ้นอย่างมีนัยสำคัญ
- โซนนี้มีความเสี่ยงสูง

| Level | Call OI | Put OI |
|-------|---------|--------|
| 2300  | 5000    | 2000   |
| 2350  | 3000    | 4000   |
'''
    img_bytes = generate_image(text)
    with open('test_export.png', 'wb') as f:
        f.write(img_bytes)
