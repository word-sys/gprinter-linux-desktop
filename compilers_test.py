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

if __name__ == "__main__":
    unittest.main()
