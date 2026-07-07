import os
from PIL import Image, ImageOps

def get_bitmap_command(x, y, image_or_path, target_width=200, invert=False, mode=0):
    try:
        if isinstance(image_or_path, str):
            if not os.path.exists(image_or_path):
                return b""
            img = Image.open(image_or_path)
        else:
            img = image_or_path

        w_percent = target_width / float(img.size[0])
        h_size = int(float(img.size[1]) * float(w_percent))
        try:
            resample_filter = Image.Resampling.LANCZOS
        except AttributeError:
            resample_filter = getattr(Image, 'LANCZOS', getattr(Image, 'ANTIALIAS', 0))
            
        img = img.resize((target_width, h_size), resample_filter).convert('1')
        if invert:
            img = ImageOps.invert(img.convert('L')).convert('1')

        width, height = img.size
        width_bytes = (width + 7) // 8
        cmd_header = f"BITMAP {x},{y},{width_bytes},{height},{mode},".encode('ascii')
        
        img_data = bytearray()
        for y_idx in range(height):
            current_byte = 0
            for x_idx in range(width_bytes * 8):
                if x_idx < width:
                    if img.getpixel((x_idx, y_idx)) == 0:
                        current_byte |= (1 << (7 - (x_idx % 8)))
                if (x_idx % 8) == 7:
                    img_data.append(current_byte)
                    current_byte = 0
        return cmd_header + bytes(img_data) + b"\r\n"
    except Exception:
        return b""

def compile_label(width_mm, height_mm, gap_mm, elements):
    out = bytearray()
    out.extend(f"SIZE {width_mm} mm,{height_mm} mm\r\n".encode('ascii'))
    if gap_mm > 0:
        out.extend(f"GAP {gap_mm} mm,0 mm\r\n".encode('ascii'))
    else:
        out.extend(b"GAP 0,0\r\n")
    out.extend(b"DIRECTION 1\r\n")
    out.extend(b"CLS\r\n")
    
    for el in elements:
        etype = el.get("type", "text")
        x = el.get("x", 0)
        y = el.get("y", 0)
        if etype == "text":
            text = el.get("text", "")
            font = el.get("font", "1")
            rot = el.get("rotation", 0)
            mx = el.get("mx", 1)
            my = el.get("my", 1)
            escaped_text = text.replace('"', '\\"')
            out.extend(f'TEXT {x},{y},"{font}",{rot},{mx},{my},"{escaped_text}"\r\n'.encode('utf-8'))
        elif etype == "barcode":
            content = el.get("content", "")
            btype = el.get("btype", "128")
            h = el.get("height", 50)
            read = el.get("readable", 1)
            rot = el.get("rotation", 0)
            narrow = el.get("narrow", 2)
            wide = el.get("wide", 6)
            escaped_content = content.replace('"', '\\"')
            out.extend(f'BARCODE {x},{y},"{btype}",{h},{read},{rot},{narrow},{wide},"{escaped_content}"\r\n'.encode('utf-8'))
        elif etype == "qrcode":
            content = el.get("content", "")
            ecc = el.get("ecc", "M")
            cell_w = el.get("cell_width", 4)
            rot = el.get("rotation", 0)
            escaped_content = content.replace('"', '\\"')
            out.extend(f'QRCODE {x},{y},{ecc},{cell_w},A,{rot},"{escaped_content}"\r\n'.encode('utf-8'))
        elif etype == "image":
            img_path_or_obj = el.get("image")
            w = el.get("width", 200)
            invert = el.get("invert", False)
            mode = el.get("mode", 0)
            bmp_bytes = get_bitmap_command(x, y, img_path_or_obj, w, invert, mode)
            if bmp_bytes:
                out.extend(bmp_bytes)
                
    out.extend(b"PRINT 1,1\r\n")
    return bytes(out)
