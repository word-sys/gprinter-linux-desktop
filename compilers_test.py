import unittest
from PIL import Image
import escpos_gen
import tspl_gen

class TestCompilers(unittest.TestCase):
    def test_escpos_compile_text(self):
        items = [{"type": "text", "text": "Hello", "align": "center", "bold": True}]
        data = escpos_gen.compile_receipt(items, 384)
        self.assertIn(escpos_gen.ESC_INIT, data)
        self.assertIn(escpos_gen.ALIGN_CENTER, data)
        self.assertIn(escpos_gen.TXT_BOLD_ON, data)
        self.assertIn(b"Hello\n", data)

    def test_escpos_turkish_encoding(self):
        items = [{"type": "text", "text": "Şişli şube"}]
        data = escpos_gen.compile_receipt(items, 384)
        self.assertIn(escpos_gen.TURKISH_INIT, data)
        self.assertIn("Şişli şube".encode("cp1254"), data)

    def test_escpos_separator(self):
        items = [{"type": "separator"}]
        data = escpos_gen.compile_receipt(items, 384)
        self.assertIn(b"-" * 48, data)
        self.assertNotIn(b"-" * 49, data)
        
        data_large = escpos_gen.compile_receipt(items, 832)
        self.assertIn(b"-" * 64, data_large)

    def test_tspl_compile_label(self):
        elements = [
            {"type": "text", "text": "LabelText", "x": 10, "y": 20, "font": "1", "rotation": 90, "mx": 1, "my": 1}
        ]
        data = tspl_gen.compile_label(40.0, 30.0, 2.0, elements)
        self.assertIn(b"SIZE 40.0 mm,30.0 mm\r\n", data)
        self.assertIn(b"GAP 2.0 mm,0 mm\r\n", data)
        self.assertIn(b"CLS\r\n", data)
        self.assertIn(b'TEXT 10,20,"1",90,1,1,"LabelText"\r\n', data)
        self.assertIn(b"PRINT 1,1\r\n", data)

    def test_monochrome_image(self):
        img = Image.new('RGB', (100, 100), color='white')
        bytes_esc = escpos_gen.get_image_bytes(img, 100)
        self.assertTrue(len(bytes_esc) > 0)
        
        bytes_tspl = tspl_gen.get_bitmap_command(10, 10, img, 100)
        self.assertTrue(len(bytes_tspl) > 0)

    def test_escpos_parse_receipt_roundtrip(self):
        """Compile a receipt, parse it back, verify key elements survive."""
        items = [
            {"type": "text", "text": "STORE NAME", "align": "center", "bold": True, "double_width": False, "double_height": False},
            {"type": "separator"},
            {"type": "text", "text": "Item A", "right_text": "$5.00", "align": "left", "bold": False, "double_width": False, "double_height": False},
            {"type": "feed", "lines": 3},
        ]
        data = escpos_gen.compile_receipt(items, 384, 48, 0)
        parsed = escpos_gen.parse_receipt(data)
        types_parsed = [p["type"] for p in parsed]
        self.assertIn("text", types_parsed)
        self.assertIn("separator", types_parsed)
        self.assertIn("feed", types_parsed)
        # Check that at least one text item has the original text content
        texts = [p["text"] for p in parsed if p["type"] == "text"]
        self.assertTrue(any("STORE NAME" in t for t in texts))

    def test_escpos_autocut_parsed(self):
        """Verify autocut command GS V 66 0 is parsed as cut item."""
        data = escpos_gen.compile_receipt([], 384) + b'\x1D\x56\x42\x00'
        parsed = escpos_gen.parse_receipt(data)
        types_parsed = [p["type"] for p in parsed]
        self.assertIn("cut", types_parsed)

    def test_tspl_parse_label_roundtrip(self):
        """Compile a TSPL label, parse it back, verify dimensions and elements."""
        elements = [
            {"type": "text", "text": "LABEL", "x": 20, "y": 30, "font": "2", "rotation": 0, "mx": 1, "my": 1},
            {"type": "barcode", "content": "123456", "btype": "128", "x": 20, "y": 80, "height": 50, "readable": 1, "rotation": 0, "narrow": 2, "wide": 6},
            {"type": "qrcode", "content": "https://example.com", "x": 200, "y": 80, "cell_width": 4, "rotation": 0, "ecc": "M"},
        ]
        data = tspl_gen.compile_label(60.0, 40.0, 3.0, elements)
        w_mm, h_mm, g_mm, parsed_els = tspl_gen.parse_label(data)
        self.assertAlmostEqual(w_mm, 60.0)
        self.assertAlmostEqual(h_mm, 40.0)
        self.assertAlmostEqual(g_mm, 3.0)
        types_parsed = [e["type"] for e in parsed_els]
        self.assertIn("text", types_parsed)
        self.assertIn("barcode", types_parsed)
        self.assertIn("qrcode", types_parsed)
        text_els = [e for e in parsed_els if e["type"] == "text"]
        self.assertEqual(text_els[0]["text"], "LABEL")
        bar_els = [e for e in parsed_els if e["type"] == "barcode"]
        self.assertEqual(bar_els[0]["content"], "123456")

if __name__ == "__main__":
    unittest.main()
