import os
from PIL import Image, ImageOps

ESC_INIT = b'\x1B\x40'
ALIGN_LEFT = b'\x1B\x61\x00'
ALIGN_CENTER = b'\x1B\x61\x01'
ALIGN_RIGHT = b'\x1B\x61\x02'
TXT_BOLD_ON = b'\x1B\x45\x01'
TXT_BOLD_OFF = b'\x1B\x45\x00'

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
    out = bytearray(ESC_INIT)

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
                out.extend(line_str.encode('utf-8') + b"\n")
            else:
                if align == "center":
                    out.extend(ALIGN_CENTER)
                elif align == "right":
                    out.extend(ALIGN_RIGHT)
                else:
                    out.extend(ALIGN_LEFT)
                out.extend(TXT_BOLD_ON if bold else TXT_BOLD_OFF)
                out.extend(get_text_size_command(dw, dh))
                out.extend(text.encode('utf-8') + b"\n")
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
