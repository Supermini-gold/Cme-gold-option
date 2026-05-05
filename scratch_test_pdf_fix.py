import os
from pdf_export import generate_pdf

text = """**Gold Options Analysis Report**

Snapshot
สรุป Bias: Bullish

Expected Range
- แนวรับ: 2300
- แนวต้าน: 2350

| Strike | Call OI | Put OI |
|--------|---------|--------|
| 2300   | 15000   | 5000   |
| 2350   | 8000    | 12000  |

คำแนะนำ
• สะสม Buy เมื่อย่อตัว
"""

try:
    pdf_bytes = generate_pdf(text, "2026-05-05 18:30:00")
    with open('test_premium_fix.pdf', 'wb') as f:
        f.write(pdf_bytes)
    print("✅ PDF generated: test_premium_fix.pdf")
except Exception as e:
    print(f"❌ Error: {str(e)}")
    import traceback
    traceback.print_exc()
