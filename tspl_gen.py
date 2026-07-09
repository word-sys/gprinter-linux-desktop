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
        elif etype == "cut":
            out.extend(b"CUT\r\n")
                
    out.extend(b"PRINT 1,1\r\n")
    return bytes(out)

def parse_label(data):
    elements = []
    width_mm = 40.0
    height_mm = 30.0
    gap_mm = 2.0
    
    i = 0
    while i < len(data):
        next_nl = data.find(b'\n', i)
        if next_nl == -1:
            line_bytes = data[i:]
            i = len(data)
        else:
            line_bytes = data[i:next_nl+1]
            i = next_nl + 1
            
        line = line_bytes.decode('utf-8', errors='replace').strip()
        if not line:
            continue
            
        if line.startswith("SIZE"):
            try:
                parts = line.replace("SIZE", "").strip().split(",")
                w_str = parts[0].replace("mm", "").strip()
                h_str = parts[1].replace("mm", "").strip()
                width_mm = float(w_str)
                height_mm = float(h_str)
            except Exception:
                pass
        elif line.startswith("GAP"):
            try:
                parts = line.replace("GAP", "").strip().split(",")
                g_str = parts[0].replace("mm", "").strip()
                gap_mm = float(g_str)
            except Exception:
                pass
        elif line.startswith("TEXT"):
            try:
                cmd_content = line[4:].strip()
                tokens = []
                in_quote = False
                curr = []
                for char in cmd_content:
                    if char == '"':
                        in_quote = not in_quote
                    elif char == ',' and not in_quote:
                        tokens.append("".join(curr).strip())
                        curr = []
                    else:
                        curr.append(char)
                if curr:
                    tokens.append("".join(curr).strip())
                
                if len(tokens) >= 7:
                    x = int(tokens[0])
                    y = int(tokens[1])
                    font = tokens[2].strip('"')
                    rot = int(tokens[3])
                    mx = int(tokens[4])
                    my = int(tokens[5])
                    text = tokens[6].strip('"').replace('\\"', '"')
                    elements.append({
                        "type": "text",
                        "x": x,
                        "y": y,
                        "font": font,
                        "rotation": rot,
                        "mx": mx,
                        "my": my,
                        "text": text
                    })
            except Exception as e:
                print(f"Error parsing TEXT: {e}")
        elif line.startswith("BARCODE"):
            try:
                cmd_content = line[7:].strip()
                tokens = []
                in_quote = False
                curr = []
                for char in cmd_content:
                    if char == '"':
                        in_quote = not in_quote
                    elif char == ',' and not in_quote:
                        tokens.append("".join(curr).strip())
                        curr = []
                    else:
                        curr.append(char)
                if curr:
                    tokens.append("".join(curr).strip())
                
                if len(tokens) >= 9:
                    elements.append({
                        "type": "barcode",
                        "x": int(tokens[0]),
                        "y": int(tokens[1]),
                        "btype": tokens[2].strip('"'),
                        "height": int(tokens[3]),
                        "readable": int(tokens[4]),
                        "rotation": int(tokens[5]),
                        "narrow": int(tokens[6]),
                        "wide": int(tokens[7]),
                        "content": tokens[8].strip('"').replace('\\"', '"')
                    })
            except Exception as e:
                print(f"Error parsing BARCODE: {e}")
        elif line.startswith("QRCODE"):
            try:
                cmd_content = line[6:].strip()
                tokens = []
                in_quote = False
                curr = []
                for char in cmd_content:
                    if char == '"':
                        in_quote = not in_quote
                    elif char == ',' and not in_quote:
                        tokens.append("".join(curr).strip())
                        curr = []
                    else:
                        curr.append(char)
                if curr:
                    tokens.append("".join(curr).strip())
                
                if len(tokens) >= 7:
                    elements.append({
                        "type": "qrcode",
                        "x": int(tokens[0]),
                        "y": int(tokens[1]),
                        "ecc": tokens[2],
                        "cell_width": int(tokens[3]),
                        "rotation": int(tokens[5]),
                        "content": tokens[6].strip('"').replace('\\"', '"')
                    })
            except Exception as e:
                print(f"Error parsing QRCODE: {e}")
        elif line.startswith("CUT"):
            elements.append({
                "type": "cut"
            })
        elif line.startswith("BITMAP"):
            try:
                header_parts = line.split(",")
                x = int(header_parts[0].replace("BITMAP", "").strip())
                y = int(header_parts[1].strip())
                width_bytes = int(header_parts[2].strip())
                height = int(header_parts[3].strip())
                mode = int(header_parts[4].strip())
                
                header_prefix = f"BITMAP {x},{y},{width_bytes},{height},{mode},".encode('ascii')
                header_pos = data.find(header_prefix, i - len(line_bytes) - 10)
                if header_pos != -1:
                    binary_start = header_pos + len(header_prefix)
                    pixel_bytes_len = width_bytes * height
                    pixel_data = data[binary_start:binary_start + pixel_bytes_len]
                    
                    img = Image.new('1', (width_bytes * 8, height), 1)
                    for y_idx in range(height):
                        for xb in range(width_bytes):
                            idx = y_idx * width_bytes + xb
                            if idx < len(pixel_data):
                                b_val = pixel_data[idx]
                                for bit in range(8):
                                    px_x = xb * 8 + bit
                                    if (b_val & (1 << (7 - bit))) != 0:
                                        img.putpixel((px_x, y_idx), 0)
                                        
                    elements.append({
                        "type": "image",
                        "x": x,
                        "y": y,
                        "width": width_bytes * 8,
                        "image": img,
                        "invert": False,
                        "mode": mode
                    })
                    
                    i = binary_start + pixel_bytes_len
                    if data[i:i+2] == b'\r\n':
                        i += 2
                    elif data[i:i+1] == b'\n':
                        i += 1
            except Exception as e:
                print(f"Error parsing BITMAP: {e}")
                
    return width_mm, height_mm, gap_mm, elements

