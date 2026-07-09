import os
from PIL import Image, ImageOps

ESC_INIT = b'\x1B\x40'
TURKISH_INIT = b'\x1B\x40\x1C\x2E\x1B\x74\x26'
ALIGN_LEFT = b'\x1B\x61\x00'
ALIGN_CENTER = b'\x1B\x61\x01'
ALIGN_RIGHT = b'\x1B\x61\x02'
TXT_BOLD_ON = b'\x1B\x45\x01'
TXT_BOLD_OFF = b'\x1B\x45\x00'


def encode_text(text):
    return str(text).encode('cp1254', errors='replace')

def get_text_size_command(double_w=False, double_h=False):
    val = 0
    if double_w: val |= 0x10
    if double_h: val |= 0x01
    return bytes([0x1D, 0x21, val])

def get_feed_command(lines=1):
    return bytes([0x1B, 0x64, max(1, min(lines, 255))])

def get_image_bytes(image_or_path, target_width=384, invert=False, width=None, height=None, keep_aspect=True, left_margin=0):
    try:
        if isinstance(image_or_path, str):
            if not os.path.exists(image_or_path):
                return b""
            img = Image.open(image_or_path)
        else:
            img = image_or_path

        max_w = max(1, target_width - left_margin)
        w = width if width is not None else max_w
        w = min(w, max_w)

        if keep_aspect:
            w_percent = w / float(img.size[0])
            h = int(float(img.size[1]) * float(w_percent))
        else:
            h = height if height is not None else img.size[1]
        
        w = max(1, w)
        h = max(1, h)

        try:
            resample_filter = Image.Resampling.LANCZOS
        except AttributeError:
            resample_filter = getattr(Image, 'LANCZOS', getattr(Image, 'ANTIALIAS', 0))
        
        img = img.resize((w, h), resample_filter).convert('1')
        if invert:
            img = ImageOps.invert(img.convert('L')).convert('1')
            
        width, height = img.size
        width_bytes = (width + 7) // 8
        header = bytes([0x1D, 0x76, 0x30, 0, width_bytes % 256, width_bytes // 256, height % 256, height // 256])
        
        img_data = bytearray()
        for y in range(height):
            current_byte = 0
            for x in range(width_bytes * 8):
                if x < width:
                    if img.getpixel((x, y)) == 0:
                        current_byte |= (1 << (7 - (x % 8)))
                if (x % 8) == 7:
                    img_data.append(current_byte)
                    current_byte = 0
        return header + bytes(img_data) + b"\n"
    except Exception:
        return b""

def compile_receipt(items, target_width=384, chars_per_line=None, left_margin=0):
    if chars_per_line is None:
        chars_per_line = 48 if target_width <= 576 else 64
    c_per_line = chars_per_line
    sep = (b"-" * c_per_line) + b"\n"
    out = bytearray(TURKISH_INIT)

    if left_margin > 0:
        nL = left_margin % 256
        nH = left_margin // 256
        out.extend(bytes([0x1D, 0x4C, nL, nH]))
    
    for item in items:
        itype = item.get("type", "text")
        if itype == "text":
            align = item.get("align", "left")
            bold = item.get("bold", False)
            dw = item.get("double_width", False)
            dh = item.get("double_height", False)
            text = item.get("text", "")
            right_text = item.get("right_text", "")
            
            if right_text:
                c_limit = c_per_line // 2 if dw else c_per_line
                spaces = c_limit - len(text) - len(right_text)
                line_str = text + " " * max(1, spaces) + right_text
                out.extend(ALIGN_LEFT)
                out.extend(TXT_BOLD_ON if bold else TXT_BOLD_OFF)
                out.extend(get_text_size_command(dw, dh))
                out.extend(encode_text(line_str) + b"\n")
            else:
                if align == "center":
                    out.extend(ALIGN_CENTER)
                elif align == "right":
                    out.extend(ALIGN_RIGHT)
                else:
                    out.extend(ALIGN_LEFT)
                out.extend(TXT_BOLD_ON if bold else TXT_BOLD_OFF)
                out.extend(get_text_size_command(dw, dh))
                out.extend(encode_text(text) + b"\n")
        elif itype == "separator":
            out.extend(ALIGN_LEFT)
            out.extend(TXT_BOLD_OFF)
            out.extend(get_text_size_command(False, False))
            out.extend(sep)
        elif itype == "image":
            img_path_or_obj = item.get("image")
            invert = item.get("invert", False)
            align = item.get("align", "center")
            width = item.get("width")
            height = item.get("height")
            keep_aspect = item.get("keep_aspect", True)

            if align == "left":
                out.extend(ALIGN_LEFT)
            elif align == "right":
                out.extend(ALIGN_RIGHT)
            else:
                out.extend(ALIGN_CENTER)

            img_bytes = get_image_bytes(img_path_or_obj, target_width, invert, width, height, keep_aspect, left_margin)
            if img_bytes:
                out.extend(img_bytes)
        elif itype == "feed":
            lines = item.get("lines", 1)
            out.extend(get_feed_command(lines))
            
    return bytes(out)

def parse_receipt(data):
    items = []
    i = 0
    align = "left"
    bold = False
    double_width = False
    double_height = False
    
    accumulated_text = bytearray()
    
    def flush_text():
        nonlocal accumulated_text
        if accumulated_text:
            try:
                text_str = accumulated_text.decode('cp1254', errors='replace')
            except Exception:
                text_str = accumulated_text.decode('utf-8', errors='replace')
            accumulated_text = bytearray()
            
            lines = text_str.split('\n')
            for idx, line in enumerate(lines):
                if idx == len(lines) - 1 and not line:
                    break
                line_stripped = line.strip()
                if line_stripped and all(c == '-' for c in line_stripped) and len(line_stripped) >= 16:
                    items.append({"type": "separator"})
                else:
                    if "   " in line:
                        parts = [p.strip() for p in line.split("   ") if p.strip()]
                        if len(parts) == 2:
                            items.append({
                                "type": "text",
                                "text": parts[0],
                                "right_text": parts[1],
                                "align": "left",
                                "bold": bold,
                                "double_width": double_width,
                                "double_height": double_height
                            })
                            continue
                    
                    items.append({
                        "type": "text",
                        "text": line,
                        "align": align,
                        "bold": bold,
                        "double_width": double_width,
                        "double_height": double_height
                    })

    while i < len(data):
        if data[i:i+2] == b'\x1B\x40':  
            flush_text()
            bold = False
            double_width = False
            double_height = False
            align = "left"
            i += 2
        elif data[i:i+3] == b'\x1B\x61\x00':  
            flush_text()
            align = "left"
            i += 3
        elif data[i:i+3] == b'\x1B\x61\x01':  
            flush_text()
            align = "center"
            i += 3
        elif data[i:i+3] == b'\x1B\x61\x02':  
            flush_text()
            align = "right"
            i += 3
        elif data[i:i+3] == b'\x1B\x45\x01':  
            flush_text()
            bold = True
            i += 3
        elif data[i:i+3] == b'\x1B\x45\x00':  
            flush_text()
            bold = False
            i += 3
        elif data[i:i+2] == b'\x1D\x21' and i + 2 < len(data):  
            flush_text()
            val = data[i+2]
            double_width = bool(val & 0x10)
            double_height = bool(val & 0x01)
            i += 3
        elif data[i:i+2] == b'\x1B\x64' and i + 2 < len(data):  
            flush_text()
            lines = data[i+2]
            items.append({"type": "feed", "lines": lines})
            i += 3
        elif data[i:i+2] == b'\x1D\x56' and i + 2 < len(data): 
            flush_text()
            m = data[i+2]
            if m in (0, 1, 48, 49):
                i += 3
            elif m in (65, 66) and i + 3 < len(data):
                i += 4
            else:
                i += 3
            items.append({"type": "cut"})
        elif data[i:i+4] == b'\x1D\x76\x30\x00' and i + 8 < len(data):  
            flush_text()
            width_bytes = data[i+4] + data[i+5] * 256
            height = data[i+6] + data[i+7] * 256
            pixel_bytes_len = width_bytes * height
            pixel_data = data[i+8 : i+8+pixel_bytes_len]
            
            try:
                img = Image.new('1', (width_bytes * 8, height), 1)
                for y in range(height):
                    for xb in range(width_bytes):
                        idx = y * width_bytes + xb
                        if idx < len(pixel_data):
                            b_val = pixel_data[idx]
                            for bit in range(8):
                                px_x = xb * 8 + bit
                                if (b_val & (1 << (7 - bit))) != 0:
                                    img.putpixel((px_x, y), 0)
                items.append({
                    "type": "image",
                    "image": img,
                    "align": align,
                    "invert": False,
                    "keep_aspect": True
                })
            except Exception as e:
                print(f"Error parsing image: {e}")
            i += 8 + pixel_bytes_len
        elif data[i:i+3] == b'\x1C\x2E\x1B':  
            i += 1
        elif data[i:i+2] == b'\x1B\x74':  
            i += 3
        else:
            accumulated_text.append(data[i])
            i += 1
            
    flush_text()
    return items

