import os
import io
from image_export import generate_image

text = """**Gold Options Analysis Report**

Snapshot
สรุป Bias: [Bullish] ตลาดมีแนวโน้มปรับตัวขึ้นต่อจากแรงซื้อ Institutional

Expected Range
- แนวรับสำคัญ: 2300, 2315
- แนวต้านสำคัญ: 2350, 2380
- คาดการณ์การเคลื่อนไหว: Sideway Up

Key Levels & Volume
- มีปริมาณ Call Volume หนาแน่นที่ 2400
- Put Volume กระจุกตัวที่ 2250

| Strike | Call OI | Put OI | Status |
|--------|---------|--------|--------|
| 2300   | 15000   | 5000   | Support|
| 2350   | 8000    | 12000  | Neutral|
| 2400   | 25000   | 2000   | Resistance|

กลยุทธ์แนะนำ
• เปิด Long เมื่อย่อตัวใกล้ 2315
• Hedging ด้วย Put Options ที่ 2280 หากหลุดแนวรับ
"""

try:
    img_bytes = generate_image(text, "2026-05-05 18:30:00")
    with open('test_premium_export.png', 'wb') as f:
        f.write(img_bytes)
    print("✅ Premium image generated: test_premium_export.png")
except Exception as e:
    print(f"❌ Error: {str(e)}")
    import traceback
    traceback.print_exc()
