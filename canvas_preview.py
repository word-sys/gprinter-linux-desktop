import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GdkPixbuf
import cairo
import math
from PIL import Image, ImageOps

def pil_to_cairo_surface(pil_img):
    rgba = pil_img.convert("RGBA")
    data = bytearray(rgba.tobytes())
    for i in range(0, len(data), 4):
        r, g, b, a = data[i], data[i+1], data[i+2], data[i+3]
        data[i] = b
        data[i+1] = g
        data[i+2] = r
        data[i+3] = a
    return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, rgba.width, rgba.height)

CANVAS_W        = 390
LINE_H          = 22
LINE_H_DH       = 36
SEP_H           = 16
FEED_PX_PER_LINE = 14
PADDING         = 16
_BG      = (0.80, 0.81, 0.83)   
_PAPER   = (0.995, 0.985, 0.960) 
_SHADOW  = (0.0, 0.0, 0.0, 0.22)
_TEXT    = (0.08, 0.08, 0.10)
_SEP_CLR = (0.55, 0.55, 0.60)
_HOLE    = (0.72, 0.73, 0.75)
_HOLE_R   = 3.5
_HOLE_GAP = 18
_TOOTH_W  = 9
_TOOTH_H  = 5
_TOP_STRIP = 22   

class PrinterPreviewCanvas(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.mode = "receipt"
        self.receipt_items = []
        self.target_width = 384
        self.chars_per_line = 48
        self.left_margin = 0
        self.label_width_mm = 40
        self.label_height_mm = 30
        self.label_elements = []
        self.connect("draw", self.on_draw)

    def set_receipt_items(self, items, target_width, chars_per_line=None, left_margin=0):
        self.mode = "receipt"
        self.receipt_items = items
        self.target_width = target_width
        self.left_margin = left_margin
        if chars_per_line is not None:
            self.chars_per_line = chars_per_line
        else:
            self.chars_per_line = 48 if target_width <= 576 else 64
        self.set_size_request(CANVAS_W, self._receipt_height())
        self.queue_draw()

    def set_label_data(self, w_mm, h_mm, elements):
        self.mode = "label"
        self.label_width_mm = w_mm
        self.label_height_mm = h_mm
        self.label_elements = elements
        self.set_size_request(-1, -1)
        self.queue_draw()

    def on_draw(self, widget, ctx):
        if self.mode == "receipt":
            self.draw_receipt(ctx)
        else:
            self.draw_label(ctx)

    def _receipt_height(self):
        h = PADDING * 2
        for item in self.receipt_items:
            itype = item.get("type", "text")
            if itype == "text":
                h += LINE_H_DH if item.get("double_height") else LINE_H
            elif itype == "separator":
                h += SEP_H
            elif itype == "image":
                src = item.get("image")
                try:
                    img = Image.open(src) if isinstance(src, str) else src
                    max_w = max(1, self.target_width - self.left_margin)
                    w_dots = item.get("width")
                    if w_dots is None:
                        w_dots = max_w
                    w_dots = min(w_dots, max_w)

                    if item.get("keep_aspect", True):
                        h_dots = int(img.size[1] * (w_dots / float(img.size[0])))
                    else:
                        h_dots = item.get("height")
                        if h_dots is None:
                            h_dots = img.size[1]

                    preview_h = int((CANVAS_W - PADDING * 2) * (h_dots / float(self.target_width)))
                    h += preview_h + PADDING
                except Exception:
                    h += LINE_H
            elif itype == "feed":
                h += item.get("lines", 1) * FEED_PX_PER_LINE
        return max(h, 60)

    def _draw_paper_shadow(self, ctx, px, py, pw, ph):
        for i, alpha in enumerate([0.10, 0.07, 0.04]):
            off = (i + 1) * 2
            ctx.set_source_rgba(0, 0, 0, alpha)
            ctx.rectangle(px + off, py + off, pw, ph)
            ctx.fill()

    def _draw_feed_holes(self, ctx, px, py, pw):
        ctx.set_source_rgb(*_HOLE)
        x = px + _HOLE_GAP
        cy = py + _TOP_STRIP / 2
        while x < px + pw - _HOLE_GAP / 2:
            ctx.arc(x, cy, _HOLE_R, 0, 2 * math.pi)
            ctx.fill()
            x += _HOLE_GAP

    def _draw_torn_bottom(self, ctx, px, py, pw, bg):
        tw, th = _TOOTH_W, _TOOTH_H
        n = max(1, int(pw / tw))
        ctx.new_path()
        ctx.move_to(px, py)
        for i in range(n):
            ctx.line_to(px + i * tw + tw / 2, py + th)
            ctx.line_to(px + (i + 1) * tw,    py)
        ctx.line_to(px + pw, py + th + 4)
        ctx.line_to(px + pw, py + th + 10)
        ctx.line_to(px,      py + th + 10)
        ctx.close_path()
        ctx.set_source_rgb(*bg)
        ctx.fill()

    def _draw_separator_line(self, ctx, px, cy, pw):
        margin_px = int((CANVAS_W - PADDING * 2) * (self.left_margin / float(self.target_width)))
        avail_w = CANVAS_W - PADDING * 2 - margin_px
        px_start = px + PADDING + margin_px

        ctx.save()
        ctx.set_source_rgb(*_SEP_CLR)
        ctx.set_line_width(0.9)
        ctx.set_dash([4.0, 3.5])
        ctx.move_to(px_start, cy)
        ctx.line_to(px_start + avail_w, cy)
        ctx.stroke()
        ctx.set_dash([])
        ctx.restore()

    def draw_receipt(self, ctx):
        alloc = self.get_allocation()
        w = alloc.width

        ctx.set_source_rgb(*_BG)
        ctx.paint()

        px = max(0, (w - CANVAS_W) // 2)
        total_h = self._receipt_height()
        py = 14
        paper_h = _TOP_STRIP + total_h + _TOOTH_H + 4

        self._draw_paper_shadow(ctx, px, py, CANVAS_W, paper_h)

        ctx.set_source_rgb(*_PAPER)
        ctx.rectangle(px, py, CANVAS_W, paper_h)
        ctx.fill()

        ctx.set_source_rgba(*_SEP_CLR, 0.5)
        ctx.set_line_width(0.6)
        ctx.set_dash([2.0, 2.0])
        ctx.move_to(px + PADDING, py + _TOP_STRIP)
        ctx.line_to(px + CANVAS_W - PADDING, py + _TOP_STRIP)
        ctx.stroke()
        ctx.set_dash([])

        self._draw_feed_holes(ctx, px, py, CANVAS_W)

        self._draw_torn_bottom(ctx, px, py + paper_h - _TOOTH_H - 4, CANVAS_W, _BG)

        ctx.set_source_rgb(*_TEXT)
        curr_y = py + _TOP_STRIP + PADDING

        for item in self.receipt_items:
            itype = item.get("type", "text")
            if itype == "text":
                self._draw_receipt_text(ctx, item, px, curr_y, CANVAS_W)
                curr_y += LINE_H_DH if item.get("double_height") else LINE_H
            elif itype == "separator":
                self._draw_separator_line(ctx, px, curr_y + SEP_H // 2, CANVAS_W)
                curr_y += SEP_H
            elif itype == "image":
                src = item.get("image")
                invert = item.get("invert", False)
                align = item.get("align", "center")
                try:
                    img = Image.open(src) if isinstance(src, str) else src
                    img = img.convert("RGB")

                    max_w = max(1, self.target_width - self.left_margin)
                    w_dots = item.get("width")
                    if w_dots is None:
                        w_dots = max_w
                    w_dots = min(w_dots, max_w)

                    if item.get("keep_aspect", True):
                        h_dots = int(img.size[1] * (w_dots / float(img.size[0])))
                    else:
                        h_dots = item.get("height")
                        if h_dots is None:
                            h_dots = img.size[1]

                    preview_w = int((CANVAS_W - PADDING * 2) * (w_dots / float(self.target_width)))
                    preview_h = int((CANVAS_W - PADDING * 2) * (h_dots / float(self.target_width)))

                    preview_w = max(1, preview_w)
                    preview_h = max(1, preview_h)

                    img = img.resize((preview_w, preview_h), Image.Resampling.LANCZOS)
                    if invert:
                        img = ImageOps.invert(img)
                    surface = pil_to_cairo_surface(img)

                    margin_px = int((CANVAS_W - PADDING * 2) * (self.left_margin / float(self.target_width)))
                    avail_w = CANVAS_W - PADDING * 2 - margin_px
                    px_start = px + PADDING + margin_px

                    if align == "left":
                        img_x = px_start
                    elif align == "right":
                        img_x = px_start + (avail_w - preview_w)
                    else:  
                        img_x = px_start + (avail_w - preview_w) // 2

                    ctx.save()
                    ctx.set_source_surface(surface, img_x, curr_y)
                    ctx.paint()
                    ctx.restore()
                    curr_y += preview_h + PADDING
                except Exception:
                    curr_y += LINE_H
            elif itype == "feed":
                curr_y += item.get("lines", 1) * FEED_PX_PER_LINE

    def _draw_receipt_text(self, ctx, item, paper_x, curr_y, paper_w):
        text = item.get("text", "")
        right_text = item.get("right_text", "")
        align = item.get("align", "left")
        bold = item.get("bold", False)
        dw = item.get("double_width", False)
        dh = item.get("double_height", False)

        ctx.save()
        fw = cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL
        ctx.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, fw)
        fs = 15 if dh else 11
        ctx.set_font_size(fs)
        ctx.set_source_rgb(*_TEXT)

        baseline = curr_y + fs + 3

        margin_px = int((CANVAS_W - PADDING * 2) * (self.left_margin / float(self.target_width)))
        avail_w = CANVAS_W - PADDING * 2 - margin_px
        px_start = paper_x + PADDING + margin_px

        if right_text:
            ctx.move_to(px_start, baseline)
            ctx.show_text(text)
            ext_r = ctx.text_extents(right_text)
            ctx.move_to(px_start + avail_w - ext_r.x_advance, baseline)
            ctx.show_text(right_text)
        else:
            ext = ctx.text_extents(text)
            if align == "center":
                tx = px_start + (avail_w - ext.x_advance) / 2
            elif align == "right":
                tx = px_start + avail_w - ext.x_advance
            else:
                tx = px_start
            if dw:
                ctx.save()
                ctx.translate(tx, baseline)
                ctx.scale(1.7, 1.0)
                ctx.move_to(0, 0)
                ctx.show_text(text)
                ctx.restore()
            else:
                ctx.move_to(tx, baseline)
                ctx.show_text(text)
        ctx.restore()

    def draw_label(self, ctx):
        alloc = self.get_allocation()

        ctx.set_source_rgb(*_BG)
        ctx.paint()
        ctx.set_source_rgba(0.70, 0.70, 0.72, 0.5)
        ctx.set_line_width(0.5)
        grid = 20
        for gx in range(0, alloc.width, grid):
            ctx.move_to(gx, 0)
            ctx.line_to(gx, alloc.height)
            ctx.stroke()
        for gy in range(0, alloc.height, grid):
            ctx.move_to(0, gy)
            ctx.line_to(alloc.width, gy)
            ctx.stroke()

        dots_w = int(self.label_width_mm * 8)
        dots_h = int(self.label_height_mm * 8)

        scale_x = (alloc.width - 40) / max(dots_w, 1)
        scale_y = (alloc.height - 40) / max(dots_h, 1)
        scale = min(scale_x, scale_y)

        canvas_w = dots_w * scale
        canvas_h = dots_h * scale
        x_off = (alloc.width - canvas_w) / 2
        y_off = (alloc.height - canvas_h) / 2

        self._draw_paper_shadow(ctx, x_off, y_off, canvas_w, canvas_h)

        ctx.set_source_rgb(1, 1, 1)
        ctx.rectangle(x_off, y_off, canvas_w, canvas_h)
        ctx.fill()

        ctx.set_source_rgba(0.40, 0.40, 0.45, 0.8)
        ctx.set_line_width(1.5)
        ctx.rectangle(x_off, y_off, canvas_w, canvas_h)
        ctx.stroke()

        ctx.save()
        ctx.translate(x_off, y_off)
        ctx.scale(scale, scale)
        ctx.set_source_rgb(0, 0, 0)

        for el in self.label_elements:
            etype = el.get("type", "text")
            x = el.get("x", 0)
            y = el.get("y", 0)

            if etype == "text":
                text = el.get("text", "")
                font = el.get("font", "1")
                rot = el.get("rotation", 0)
                mx = el.get("mx", 1)
                my = el.get("my", 1)
                ctx.save()
                ctx.translate(x, y)
                ctx.rotate(math.radians(rot))
                ctx.scale(mx, my)
                ctx.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
                fs = {"1": 8, "2": 12, "3": 16, "4": 24, "5": 32}.get(font, 12)
                ctx.set_font_size(fs)
                ctx.move_to(0, fs)
                ctx.show_text(text)
                ctx.restore()

            elif etype == "barcode":
                content = el.get("content", "")
                h = el.get("height", 50)
                rot = el.get("rotation", 0)
                ctx.save()
                ctx.translate(x, y)
                ctx.rotate(math.radians(rot))
                b_w = 120
                ctx.set_source_rgb(0, 0, 0)
                ctx.rectangle(0, 0, b_w, h)
                ctx.fill()
                ctx.select_font_face("Monospace", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
                ctx.set_font_size(10)
                ext = ctx.text_extents(content)
                ctx.move_to((b_w - ext.width) / 2, h + 12)
                ctx.show_text(content)
                ctx.restore()

            elif etype == "qrcode":
                cell_w = el.get("cell_width", 4)
                rot = el.get("rotation", 0)
                ctx.save()
                ctx.translate(x, y)
                ctx.rotate(math.radians(rot))
                size = cell_w * 25
                ctx.set_source_rgb(0, 0, 0)
                ctx.rectangle(0, 0, size, size)
                ctx.fill()
                ctx.set_source_rgb(1, 1, 1)
                ctx.rectangle(cell_w * 2, cell_w * 2, cell_w * 21, cell_w * 21)
                ctx.fill()
                ctx.set_source_rgb(0, 0, 0)
                for px, py in [(cell_w*4, cell_w*4), (cell_w*15, cell_w*4), (cell_w*4, cell_w*15)]:
                    ctx.rectangle(px, py, cell_w*5, cell_w*5)
                    ctx.fill()
                    ctx.set_source_rgb(1, 1, 1)
                    ctx.rectangle(px+cell_w, py+cell_w, cell_w*3, cell_w*3)
                    ctx.fill()
                    ctx.set_source_rgb(0, 0, 0)
                    ctx.rectangle(px+cell_w*2, py+cell_w*2, cell_w, cell_w)
                    ctx.fill()
                ctx.restore()

            elif etype == "image":
                img_src = el.get("image")
                w = el.get("width", 200)
                invert = el.get("invert", False)
                try:
                    img = Image.open(img_src) if isinstance(img_src, str) else img_src
                    ratio = w / float(img.size[0])
                    h_size = int(img.size[1] * ratio)
                    img = img.resize((w, h_size), Image.Resampling.LANCZOS)
                    if invert:
                        img = ImageOps.invert(img.convert("RGB"))
                    surface = pil_to_cairo_surface(img)
                    ctx.save()
                    ctx.translate(x, y)
                    ctx.set_source_surface(surface, 0, 0)
                    ctx.paint()
                    ctx.restore()
                except Exception:
                    pass
        ctx.restore()
