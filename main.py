import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

import os
from PIL import Image
import fitz

import printer_comm
import escpos_gen
import tspl_gen
from canvas_preview import PrinterPreviewCanvas

css_provider = Gtk.CssProvider()
css_provider.load_from_data(b"""
    headerbar {
        background-color: #2e3436;
        color: #eeeeec;
        border-bottom: 1px solid #1c1f20;
    }
    headerbar label.title {
        font-weight: bold;
        color: white;
    }
    button.suggested-action {
        background-image: linear-gradient(to bottom, #3583e4, #1b6acb);
        color: white;
        border-radius: 5px;
        text-shadow: none;
    }
    button.suggested-action:hover {
        background-image: linear-gradient(to bottom, #5294e2, #3583e4);
    }
    button.destructive-action {
        background-image: linear-gradient(to bottom, #e01b24, #a51d24);
        color: white;
        border-radius: 5px;
    }
    button.destructive-action:hover {
        background-image: linear-gradient(to bottom, #ec5d5d, #e01b24);
    }
    frame {
        border: 1px solid rgba(128, 128, 128, 0.2);
        border-radius: 6px;
        padding: 8px;
    }
""")
Gtk.StyleContext.add_provider_for_screen(
    Gdk.Screen.get_default(),
    css_provider,
    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
)

class GPrinterApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="GPrinter Linuz Desktop Printer")
        self.set_default_size(1024, 768)
        
        self.current_pdf_doc = None
        self.current_pdf_page = 0
        self.pdf_invert = False
        
        self.receipt_items = [
            {"type": "text", "text": "GPrinter Shop", "align": "center", "bold": True, "double_width": True, "double_height": True},
            {"type": "separator"},
            {"type": "text", "text": "Item A", "right_text": "$100.00", "align": "left", "bold": False, "double_width": False, "double_height": False},
            {"type": "separator"},
            {"type": "text", "text": "Thank you!", "align": "center", "bold": True, "double_width": False, "double_height": False},
            {"type": "feed", "lines": 4}
        ]
        
        self.label_width_mm = 50.0
        self.label_height_mm = 40.0
        self.label_gap_mm = 2.0
        self.label_elements = [
            {"type": "text", "text": "PRODUCT LABEL", "x": 40, "y": 20, "font": "3", "rotation": 0, "mx": 1, "my": 1},
            {"type": "barcode", "content": "12345678", "btype": "128", "x": 40, "y": 80, "height": 60, "rotation": 0, "narrow": 2, "wide": 6},
            {"type": "qrcode", "content": "https://GPrinter.example", "x": 280, "y": 180, "cell_width": 4, "rotation": 0}
        ]
        
        self.chars_per_line = 48
        self.left_margin = 24
        
        self.init_ui()

    def init_ui(self):
        self.set_title("GPrinter Linux Desktop Printer")
        
        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(main_vbox)
        
        top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        top_bar.set_size_request(-1, 50)
        top_bar.set_margin_start(12)
        top_bar.set_margin_end(12)
        top_bar.set_margin_top(6)
        top_bar.set_margin_bottom(6)
        main_vbox.pack_start(top_bar, False, False, 0)
        
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        title_lbl = Gtk.Label()
        title_lbl.set_markup("<span weight='bold' size='large'>GPrinter Linux Desktop Printer</span>")
        title_lbl.set_xalign(0.0)
        subtitle_lbl = Gtk.Label(label="Linux v0.1")
        subtitle_lbl.set_xalign(0.0)
        subtitle_lbl.get_style_context().add_class("dim-label")
        title_box.pack_start(title_lbl, False, False, 0)
        title_box.pack_start(subtitle_lbl, False, False, 0)
        top_bar.pack_start(title_box, False, False, 0)
        
        self.status_label = Gtk.Label(label="Idle")
        top_bar.pack_start(self.status_label, True, True, 0)
        
        print_btn = Gtk.Button(label="Print")
        print_btn.get_style_context().add_class("suggested-action")
        print_btn.connect("clicked", self.on_print_clicked)
        top_bar.pack_end(print_btn, False, False, 0)
        
        main_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        main_vbox.pack_start(main_hbox, True, True, 0)
        
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        sidebar.set_size_request(280, -1)
        main_hbox.pack_start(sidebar, False, False, 6)
        
        conn_frame = Gtk.Frame(label="Connection Settings")
        sidebar.pack_start(conn_frame, False, False, 0)
        
        conn_grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        conn_frame.add(conn_grid)
        
        conn_grid.attach(Gtk.Label(label="Device Path:"), 0, 0, 1, 1)
        self.dev_path_entry = Gtk.Entry(text="/dev/usb/lp0")
        conn_grid.attach(self.dev_path_entry, 1, 0, 1, 1)
        
        detect_btn = Gtk.Button(label="Auto-Detect")
        detect_btn.connect("clicked", self.on_detect_clicked)
        conn_grid.attach(detect_btn, 0, 1, 1, 1)
        
        test_btn = Gtk.Button(label="Test Connection")
        test_btn.connect("clicked", self.on_test_clicked)
        conn_grid.attach(test_btn, 1, 1, 1, 1)
        
        config_frame = Gtk.Frame(label="General Print Settings")
        sidebar.pack_start(config_frame, False, False, 0)
        
        config_grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        config_frame.add(config_grid)
        
        config_grid.attach(Gtk.Label(label="Density/Width:"), 0, 0, 1, 1)
        self.width_combo = Gtk.ComboBoxText()
        self.width_combo.append("384", "2 inch (384 dots)")
        self.width_combo.append("576", "3 inch (576 dots)")
        self.width_combo.append("832", "4 inch (832 dots)")
        self.width_combo.set_active_id("832")
        self.width_combo.connect("changed", self.on_width_changed)
        config_grid.attach(self.width_combo, 1, 0, 1, 1)
        
        config_grid.attach(Gtk.Label(label="Chars/Line:"), 0, 1, 1, 1)
        self.chars_spin = Gtk.SpinButton(
            adjustment=Gtk.Adjustment(value=self.chars_per_line, lower=16, upper=128, step_increment=1)
        )
        self.chars_spin.connect("value-changed", self.on_chars_per_line_changed)
        config_grid.attach(self.chars_spin, 1, 1, 1, 1)
        
        config_grid.attach(Gtk.Label(label="Left Margin (dots):"), 0, 2, 1, 1)
        self.margin_spin = Gtk.SpinButton(
            adjustment=Gtk.Adjustment(value=self.left_margin, lower=0, upper=128, step_increment=4)
        )
        self.margin_spin.connect("value-changed", self.on_left_margin_changed)
        config_grid.attach(self.margin_spin, 1, 2, 1, 1)
        
        self.notebook = Gtk.Notebook()
        main_hbox.pack_start(self.notebook, True, True, 6)
        
        self.setup_receipt_tab()
        self.setup_label_tab()
        self.setup_pdf_tab()
        
        self.update_previews()

    def setup_receipt_tab(self):
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_margin_bottom(10)
        hbox.set_margin_start(10)
        hbox.set_margin_end(10)
        self.notebook.append_page(hbox, Gtk.Label(label="ESC/POS Receipt"))
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left_box.set_size_request(300, -1)
        left_box.set_margin_top(36)
        hbox.pack_start(left_box, False, False, 6)
        scroll = Gtk.ScrolledWindow()
        left_box.pack_start(scroll, True, True, 0)
        
        self.receipt_model = Gtk.ListStore(str, str, int)
        self.receipt_tree = Gtk.TreeView(model=self.receipt_model)
        self.receipt_tree.connect("row-activated", lambda tv, path, col: self.on_edit_receipt_item(None))
        scroll.add(self.receipt_tree)
        
        self.receipt_tree.append_column(Gtk.TreeViewColumn("Type", Gtk.CellRendererText(), text=0))
        self.receipt_tree.append_column(Gtk.TreeViewColumn("Details", Gtk.CellRendererText(), text=1))
        
        self.populate_receipt_model()
        
        btn_box = Gtk.Grid(row_spacing=4, column_spacing=4)
        left_box.pack_start(btn_box, False, False, 0)
        
        add_txt_btn = Gtk.Button(label="+ Text")
        add_txt_btn.connect("clicked", self.on_add_receipt_text)
        btn_box.attach(add_txt_btn, 0, 0, 1, 1)
        
        add_sep_btn = Gtk.Button(label="+ Sep")
        add_sep_btn.connect("clicked", self.on_add_receipt_sep)
        btn_box.attach(add_sep_btn, 1, 0, 1, 1)
        
        add_img_btn = Gtk.Button(label="+ Image")
        add_img_btn.connect("clicked", self.on_add_receipt_img)
        btn_box.attach(add_img_btn, 2, 0, 1, 1)

        add_feed_btn = Gtk.Button(label="+ Feed")
        add_feed_btn.connect("clicked", lambda w: self.run_receipt_feed_dialog())
        btn_box.attach(add_feed_btn, 3, 0, 1, 1)
        
        edit_btn = Gtk.Button(label="Edit")
        edit_btn.connect("clicked", self.on_edit_receipt_item)
        btn_box.attach(edit_btn, 0, 1, 2, 1)
        
        del_btn = Gtk.Button(label="Delete")
        del_btn.get_style_context().add_class("destructive-action")
        del_btn.connect("clicked", self.on_del_receipt_item)
        btn_box.attach(del_btn, 2, 1, 2, 1)

        move_up = Gtk.Button(label="Move Up")
        move_up.connect("clicked", self.on_move_receipt_up)
        btn_box.attach(move_up, 0, 2, 2, 1)

        move_down = Gtk.Button(label="Move Down")
        move_down.connect("clicked", self.on_move_receipt_down)
        btn_box.attach(move_down, 2, 2, 2, 1)
        
        right_scroll = Gtk.ScrolledWindow()
        right_scroll.set_margin_top(36)
        hbox.pack_start(right_scroll, True, True, 6)
        
        self.receipt_preview = PrinterPreviewCanvas()
        right_scroll.add(self.receipt_preview)

    def populate_receipt_model(self):
        self.receipt_model.clear()
        for idx, item in enumerate(self.receipt_items):
            itype = item["type"]
            details = item.get("text", item.get("image", ""))
            if itype == "text" and item.get("right_text"):
                details = f"{details} | {item['right_text']}"
            elif itype == "feed":
                details = f"{item.get('lines', 1)} lines"
            self.receipt_model.append([itype, str(details), idx])

    def setup_label_tab(self):
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_margin_bottom(10)
        hbox.set_margin_start(10)
        hbox.set_margin_end(10)
        self.notebook.append_page(hbox, Gtk.Label(label="TSPL Label"))
        
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left_box.set_size_request(320, -1)
        left_box.set_margin_top(36)
        hbox.pack_start(left_box, False, False, 6)
        
        dim_frame = Gtk.Frame(label="Label Size (mm)")
        left_box.pack_start(dim_frame, False, False, 0)
        dim_grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        dim_frame.add(dim_grid)
        
        dim_grid.attach(Gtk.Label(label="W:"), 0, 0, 1, 1)
        self.lbl_w_entry = Gtk.Entry(text=str(self.label_width_mm))
        self.lbl_w_entry.connect("changed", self.on_label_dims_changed)
        dim_grid.attach(self.lbl_w_entry, 1, 0, 1, 1)
        
        dim_grid.attach(Gtk.Label(label="H:"), 0, 1, 1, 1)
        self.lbl_h_entry = Gtk.Entry(text=str(self.label_height_mm))
        self.lbl_h_entry.connect("changed", self.on_label_dims_changed)
        dim_grid.attach(self.lbl_h_entry, 1, 1, 1, 1)
        
        dim_grid.attach(Gtk.Label(label="Gap:"), 0, 2, 1, 1)
        self.lbl_g_entry = Gtk.Entry(text=str(self.label_gap_mm))
        self.lbl_g_entry.connect("changed", self.on_label_dims_changed)
        dim_grid.attach(self.lbl_g_entry, 1, 2, 1, 1)
        
        scroll = Gtk.ScrolledWindow()
        left_box.pack_start(scroll, True, True, 0)
        
        self.label_model = Gtk.ListStore(str, str, int)
        self.label_tree = Gtk.TreeView(model=self.label_model)
        self.label_tree.connect("row-activated", lambda tv, path, col: self.on_edit_label_element(None))
        scroll.add(self.label_tree)
        
        self.label_tree.append_column(Gtk.TreeViewColumn("Type", Gtk.CellRendererText(), text=0))
        self.label_tree.append_column(Gtk.TreeViewColumn("Info", Gtk.CellRendererText(), text=1))
        
        self.populate_label_model()
        
        btn_box = Gtk.Grid(row_spacing=4, column_spacing=4)
        left_box.pack_start(btn_box, False, False, 0)
        
        add_txt = Gtk.Button(label="+ Text")
        add_txt.connect("clicked", self.on_add_label_text)
        btn_box.attach(add_txt, 0, 0, 1, 1)
        
        add_bar = Gtk.Button(label="+ Barcode")
        add_bar.connect("clicked", self.on_add_label_barcode)
        btn_box.attach(add_bar, 1, 0, 1, 1)
        
        add_qr = Gtk.Button(label="+ QR")
        add_qr.connect("clicked", self.on_add_label_qrcode)
        btn_box.attach(add_qr, 2, 0, 1, 1)
        
        add_img = Gtk.Button(label="+ Image")
        add_img.connect("clicked", self.on_add_label_img)
        btn_box.attach(add_img, 3, 0, 1, 1)
        
        edit_btn = Gtk.Button(label="Edit")
        edit_btn.connect("clicked", self.on_edit_label_element)
        btn_box.attach(edit_btn, 0, 1, 2, 1)
        
        del_btn = Gtk.Button(label="Delete")
        del_btn.get_style_context().add_class("destructive-action")
        del_btn.connect("clicked", self.on_del_label_element)
        btn_box.attach(del_btn, 2, 1, 2, 1)

        move_up = Gtk.Button(label="Move Up")
        move_up.connect("clicked", self.on_move_label_up)
        btn_box.attach(move_up, 0, 2, 2, 1)

        move_down = Gtk.Button(label="Move Down")
        move_down.connect("clicked", self.on_move_label_down)
        btn_box.attach(move_down, 2, 2, 2, 1)
        
        right_scroll = Gtk.ScrolledWindow()
        right_scroll.set_margin_top(36)
        hbox.pack_start(right_scroll, True, True, 6)
        
        self.label_preview = PrinterPreviewCanvas()
        right_scroll.add(self.label_preview)

    def populate_label_model(self):
        self.label_model.clear()
        for idx, el in enumerate(self.label_elements):
            etype = el["type"]
            info = f"({el['x']},{el['y']}) "
            if etype == "text":
                info += el["text"]
            elif etype in ["barcode", "qrcode"]:
                info += el["content"]
            elif etype == "image":
                info += str(el["image"])
            self.label_model.append([etype, info, idx])

    def setup_pdf_tab(self):
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_margin_bottom(10)
        hbox.set_margin_start(10)
        hbox.set_margin_end(10)
        self.notebook.append_page(hbox, Gtk.Label(label="Quick PDF"))
        
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left_box.set_size_request(300, -1)
        left_box.set_margin_top(36)
        hbox.pack_start(left_box, False, False, 6)
        
        choose_btn = Gtk.FileChooserButton(title="Select PDF File", action=Gtk.FileChooserAction.OPEN)
        choose_btn.connect("file-set", self.on_pdf_selected)
        left_box.pack_start(choose_btn, False, False, 0)
        
        self.page_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=0, lower=0, upper=0, step_increment=1))
        self.page_spin.connect("value-changed", self.on_pdf_page_changed)
        
        grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        left_box.pack_start(grid, False, False, 0)
        grid.attach(Gtk.Label(label="Page:"), 0, 0, 1, 1)
        grid.attach(self.page_spin, 1, 0, 1, 1)
        
        self.pdf_invert_chk = Gtk.CheckButton(label="Invert Colors (Negative)")
        self.pdf_invert_chk.connect("toggled", self.on_pdf_invert_toggled)
        grid.attach(self.pdf_invert_chk, 0, 1, 2, 1)
        
        pdf_print_btn = Gtk.Button(label="Print Selected Page")
        pdf_print_btn.get_style_context().add_class("suggested-action")
        pdf_print_btn.connect("clicked", self.on_pdf_print_clicked)
        left_box.pack_start(pdf_print_btn, False, False, 0)
        
        right_scroll = Gtk.ScrolledWindow()
        right_scroll.set_margin_top(36)
        hbox.pack_start(right_scroll, True, True, 6)
        
        self.pdf_preview = PrinterPreviewCanvas()
        right_scroll.add(self.pdf_preview)

    def on_pdf_selected(self, widget):
        path = widget.get_filename()
        if path:
            try:
                self.current_pdf_doc = fitz.open(path)
                pages = len(self.current_pdf_doc)
                self.page_spin.set_range(0, pages - 1)
                self.page_spin.set_value(0)
                self.current_pdf_page = 0
                self.update_pdf_preview()
            except Exception as e:
                self.show_error_dialog(f"Failed to load PDF: {e}")

    def on_pdf_page_changed(self, widget):
        self.current_pdf_page = int(widget.get_value())
        self.update_pdf_preview()

    def on_pdf_invert_toggled(self, widget):
        self.pdf_invert = widget.get_active()
        self.update_pdf_preview()

    def update_pdf_preview(self):
        if not self.current_pdf_doc:
            return
        try:
            page = self.current_pdf_doc.load_page(self.current_pdf_page)
            pix = page.get_pixmap(dpi=150)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            w_id = self.width_combo.get_active_id()
            tw = int(w_id) if w_id else 832
            
            items = [{"type": "image", "image": img, "invert": self.pdf_invert}]
            self.pdf_preview.set_receipt_items(items, tw, self.chars_per_line, self.left_margin)
        except Exception as e:
            self.show_error_dialog(f"Preview rendering failed: {e}")

    def on_pdf_print_clicked(self, widget):
        if not self.current_pdf_doc:
            self.show_error_dialog("No PDF document loaded.")
            return
        try:
            page = self.current_pdf_doc.load_page(self.current_pdf_page)
            pix = page.get_pixmap(dpi=200)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            w_id = self.width_combo.get_active_id()
            tw = int(w_id) if w_id else 832
            
            items = [
                {"type": "image", "image": img, "invert": self.pdf_invert},
                {"type": "feed", "lines": 4}
            ]
            data = escpos_gen.compile_receipt(items, tw, self.chars_per_line, self.left_margin)
            self.send_to_printer(data)
        except Exception as e:
            self.show_error_dialog(f"PDF print failed: {e}")

    def update_previews(self):
        w_id = self.width_combo.get_active_id()
        tw = int(w_id) if w_id else 832
        self.receipt_preview.set_receipt_items(self.receipt_items, tw, self.chars_per_line, self.left_margin)
        self.label_preview.set_label_data(self.label_width_mm, self.label_height_mm, self.label_elements)

    def on_width_changed(self, widget):
        self.update_previews()
        self.update_pdf_preview()

    def on_chars_per_line_changed(self, widget):
        self.chars_per_line = int(widget.get_value())
        self.update_previews()

    def on_left_margin_changed(self, widget):
        self.left_margin = int(widget.get_value())
        self.update_previews()
        self.update_pdf_preview()

    def on_label_dims_changed(self, widget):
        try:
            self.label_width_mm = float(self.lbl_w_entry.get_text())
            self.label_height_mm = float(self.lbl_h_entry.get_text())
            self.label_gap_mm = float(self.lbl_g_entry.get_text())
            self.update_previews()
        except ValueError:
            pass

    def on_detect_clicked(self, widget):
        printers = printer_comm.detect_printers()
        if printers:
            self.dev_path_entry.set_text(printers[0])
            self.status_label.set_text(f"Detected: {printers[0]}")
        else:
            self.status_label.set_text("No USB printer detected")
            self.show_error_dialog("No GPrinter USB printer detected.")

    def on_test_clicked(self, widget):
        path = self.dev_path_entry.get_text()
        test_bytes = escpos_gen.ESC_INIT + escpos_gen.ALIGN_CENTER + b"Connection Test OK\n" + escpos_gen.get_feed_command(4)
        self.send_to_printer(test_bytes)

    def send_to_printer(self, data):
        path = self.dev_path_entry.get_text()
        self.status_label.set_text("Printing...")
        success, err = printer_comm.write_to_printer(path, data)
        if success:
            self.status_label.set_text("Print succeeded")
        else:
            self.status_label.set_text("Print failed")
            self.show_error_dialog(f"Printing failed: {err}")

    def show_error_dialog(self, message):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Error"
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def on_print_clicked(self, widget):
        page = self.notebook.get_current_page()
        w_id = self.width_combo.get_active_id()
        tw = int(w_id) if w_id else 832
        
        if page == 0:
            data = escpos_gen.compile_receipt(self.receipt_items, tw, self.chars_per_line, self.left_margin)
            self.send_to_printer(data)
        elif page == 1:
            data = tspl_gen.compile_label(self.label_width_mm, self.label_height_mm, self.label_gap_mm, self.label_elements)
            self.send_to_printer(data)
        elif page == 2:
            self.on_pdf_print_clicked(None)

    def run_receipt_text_dialog(self, item=None):
        title = "Edit Text Block" if item else "Add Text Block"
        dialog = Gtk.Dialog(title=title, transient_for=self, flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        
        grid = Gtk.Grid(row_spacing=6, column_spacing=6, margin=12)
        dialog.get_content_area().add(grid)
        
        grid.attach(Gtk.Label(label="Left Text:"), 0, 0, 1, 1)
        entry = Gtk.Entry()
        if item:
            entry.set_text(item.get("text", ""))
        grid.attach(entry, 1, 0, 1, 1)
        
        grid.attach(Gtk.Label(label="Right Text (Optional):"), 0, 1, 1, 1)
        right_entry = Gtk.Entry()
        if item:
            right_entry.set_text(item.get("right_text", ""))
        grid.attach(right_entry, 1, 1, 1, 1)
        
        grid.attach(Gtk.Label(label="Alignment:"), 0, 2, 1, 1)
        align_combo = Gtk.ComboBoxText()
        align_combo.append("left", "Left")
        align_combo.append("center", "Center")
        align_combo.append("right", "Right")
        align_combo.set_active_id(item.get("align", "left") if item else "left")
        grid.attach(align_combo, 1, 2, 1, 1)
        
        bold_chk = Gtk.CheckButton(label="Bold")
        if item:
            bold_chk.set_active(item.get("bold", False))
        grid.attach(bold_chk, 1, 3, 1, 1)
        
        dw_chk = Gtk.CheckButton(label="Double Width")
        if item:
            dw_chk.set_active(item.get("double_width", False))
        grid.attach(dw_chk, 1, 4, 1, 1)
        
        dh_chk = Gtk.CheckButton(label="Double Height")
        if item:
            dh_chk.set_active(item.get("double_height", False))
        grid.attach(dh_chk, 1, 5, 1, 1)
        
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_val = {
                "type": "text",
                "text": entry.get_text(),
                "right_text": right_entry.get_text(),
                "align": align_combo.get_active_id(),
                "bold": bold_chk.get_active(),
                "double_width": dw_chk.get_active(),
                "double_height": dh_chk.get_active()
            }
            if item:
                item.update(new_val)
            else:
                self.receipt_items.append(new_val)
            self.populate_receipt_model()
            self.update_previews()
        dialog.destroy()

    def on_add_receipt_text(self, widget):
        self.run_receipt_text_dialog()

    def on_add_receipt_sep(self, widget):
        self.receipt_items.append({"type": "separator"})
        self.populate_receipt_model()
        self.update_previews()

    def run_receipt_image_dialog(self, item=None):
        title = "Edit Image Block" if item else "Add Image Block"
        dialog = Gtk.FileChooserDialog(title=title, transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        
        w_id = self.width_combo.get_active_id()
        tw = int(w_id) if w_id else 384

        is_edit = item is not None
        initial_custom_width = is_edit and item.get("width") is not None
        initial_width = item.get("width", tw) if (is_edit and item.get("width") is not None) else tw
        initial_keep_aspect = item.get("keep_aspect", True) if is_edit else True
        initial_height = item.get("height", 100) if (is_edit and item.get("height") is not None) else 100
        initial_align = item.get("align", "center") if is_edit else "center"
        initial_invert = item.get("invert", False) if is_edit else False

        if is_edit:
            dialog.set_filename(item.get("image", ""))

        grid = Gtk.Grid(row_spacing=6, column_spacing=6, margin=6)
        dialog.get_content_area().pack_start(grid, False, False, 0)

        invert_chk = Gtk.CheckButton(label="Invert Colors (Negative)")
        invert_chk.set_active(initial_invert)
        grid.attach(invert_chk, 0, 0, 2, 1)

        grid.attach(Gtk.Label(label="Alignment:"), 0, 1, 1, 1)
        align_combo = Gtk.ComboBoxText()
        align_combo.append("left", "Left")
        align_combo.append("center", "Center")
        align_combo.append("right", "Right")
        align_combo.set_active_id(initial_align)
        grid.attach(align_combo, 1, 1, 1, 1)

        custom_w_chk = Gtk.CheckButton(label="Use Custom Width (dots)")
        custom_w_chk.set_active(initial_custom_width)
        grid.attach(custom_w_chk, 0, 2, 1, 1)

        w_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=initial_width, lower=16, upper=tw, step_increment=8))
        w_spin.set_sensitive(initial_custom_width)
        grid.attach(w_spin, 1, 2, 1, 1)

        custom_w_chk.connect("toggled", lambda w: w_spin.set_sensitive(w.get_active()))

        keep_aspect_chk = Gtk.CheckButton(label="Keep Aspect Ratio")
        keep_aspect_chk.set_active(initial_keep_aspect)
        grid.attach(keep_aspect_chk, 0, 3, 1, 1)

        h_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=initial_height, lower=16, upper=2000, step_increment=8))
        h_spin.set_sensitive(not initial_keep_aspect)
        grid.attach(h_spin, 1, 3, 1, 1)

        keep_aspect_chk.connect("toggled", lambda w: h_spin.set_sensitive(not w.get_active()))

        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            if path or is_edit:
                new_val = {
                    "type": "image",
                    "image": path if path else item["image"],
                    "invert": invert_chk.get_active(),
                    "align": align_combo.get_active_id(),
                    "keep_aspect": keep_aspect_chk.get_active(),
                    "width": int(w_spin.get_value()) if custom_w_chk.get_active() else None,
                    "height": int(h_spin.get_value()) if not keep_aspect_chk.get_active() else None
                }
                if item:
                    item.update(new_val)
                else:
                    self.receipt_items.append(new_val)
                self.populate_receipt_model()
                self.update_previews()
        dialog.destroy()

    def on_add_receipt_img(self, widget):
        self.run_receipt_image_dialog()

    def run_receipt_feed_dialog(self, item=None):
        title = "Edit Feed Block" if item else "Add Feed Block"
        dialog = Gtk.Dialog(title=title, transient_for=self, flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        
        grid = Gtk.Grid(row_spacing=6, column_spacing=6, margin=12)
        dialog.get_content_area().add(grid)
        
        grid.attach(Gtk.Label(label="Feed Lines:"), 0, 0, 1, 1)
        spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=item.get("lines", 1) if item else 1, lower=1, upper=50, step_increment=1))
        grid.attach(spin, 1, 0, 1, 1)
        
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_val = {
                "type": "feed",
                "lines": int(spin.get_value())
            }
            if item:
                item.update(new_val)
            else:
                self.receipt_items.append(new_val)
            self.populate_receipt_model()
            self.update_previews()
        dialog.destroy()

    def on_edit_receipt_item(self, widget):
        selection = self.receipt_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            return
        idx = model.get_value(treeiter, 2)
        item = self.receipt_items[idx]
        itype = item["type"]
        
        if itype == "text":
            self.run_receipt_text_dialog(item)
        elif itype == "image":
            self.run_receipt_image_dialog(item)
        elif itype == "feed":
            self.run_receipt_feed_dialog(item)

    def on_del_receipt_item(self, widget):
        selection = self.receipt_tree.get_selection()
        model, treeiter = selection.get_selected()
        if treeiter:
            idx = model.get_value(treeiter, 2)
            del self.receipt_items[idx]
            self.populate_receipt_model()
            self.update_previews()

    def on_move_receipt_up(self, widget):
        selection = self.receipt_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            return
        idx = model.get_value(treeiter, 2)
        if idx > 0:
            self.receipt_items[idx], self.receipt_items[idx-1] = self.receipt_items[idx-1], self.receipt_items[idx]
            self.populate_receipt_model()
            self.update_previews()
            self.select_receipt_item_by_index(idx - 1)

    def on_move_receipt_down(self, widget):
        selection = self.receipt_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            return
        idx = model.get_value(treeiter, 2)
        if idx < len(self.receipt_items) - 1:
            self.receipt_items[idx], self.receipt_items[idx+1] = self.receipt_items[idx+1], self.receipt_items[idx]
            self.populate_receipt_model()
            self.update_previews()
            self.select_receipt_item_by_index(idx + 1)

    def select_receipt_item_by_index(self, index):
        treeiter = self.receipt_model.get_iter_first()
        while treeiter is not None:
            if self.receipt_model.get_value(treeiter, 2) == index:
                self.receipt_tree.get_selection().select_iter(treeiter)
                path = self.receipt_model.get_path(treeiter)
                self.receipt_tree.scroll_to_cell(path, None, False, 0.0, 0.0)
                break
            treeiter = self.receipt_model.iter_next(treeiter)

    def run_label_text_dialog(self, el=None):
        title = "Edit Label Text" if el else "Add Label Text"
        dialog = Gtk.Dialog(title=title, transient_for=self, flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        
        grid = Gtk.Grid(row_spacing=6, column_spacing=6, margin=12)
        dialog.get_content_area().add(grid)
        
        grid.attach(Gtk.Label(label="Text:"), 0, 0, 1, 1)
        entry = Gtk.Entry()
        if el:
            entry.set_text(el.get("text", ""))
        grid.attach(entry, 1, 0, 1, 1)
        
        grid.attach(Gtk.Label(label="X:"), 0, 1, 1, 1)
        x_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=el.get("x", 40) if el else 40, lower=0, upper=2000, step_increment=10))
        grid.attach(x_spin, 1, 1, 1, 1)
        
        grid.attach(Gtk.Label(label="Y:"), 0, 2, 1, 1)
        y_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=el.get("y", 40) if el else 40, lower=0, upper=2000, step_increment=10))
        grid.attach(y_spin, 1, 2, 1, 1)
        
        grid.attach(Gtk.Label(label="Font Size:"), 0, 3, 1, 1)
        font_combo = Gtk.ComboBoxText()
        for f in ["1", "2", "3", "4", "5"]:
            font_combo.append(f, f"Size {f}")
        font_combo.set_active_id(el.get("font", "3") if el else "3")
        grid.attach(font_combo, 1, 3, 1, 1)
        
        grid.attach(Gtk.Label(label="Rotation:"), 0, 4, 1, 1)
        rot_combo = Gtk.ComboBoxText()
        for r in ["0", "90", "180", "270"]:
            rot_combo.append(r, f"{r}°")
        rot_combo.set_active_id(str(el.get("rotation", 0)) if el else "0")
        grid.attach(rot_combo, 1, 4, 1, 1)
        
        grid.attach(Gtk.Label(label="Size X Mul:"), 0, 5, 1, 1)
        mx_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=el.get("mx", 1) if el else 1, lower=1, upper=10, step_increment=1))
        grid.attach(mx_spin, 1, 5, 1, 1)
        
        grid.attach(Gtk.Label(label="Size Y Mul:"), 0, 6, 1, 1)
        my_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=el.get("my", 1) if el else 1, lower=1, upper=10, step_increment=1))
        grid.attach(my_spin, 1, 6, 1, 1)
        
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_val = {
                "type": "text",
                "text": entry.get_text(),
                "x": int(x_spin.get_value()),
                "y": int(y_spin.get_value()),
                "font": font_combo.get_active_id(),
                "rotation": int(rot_combo.get_active_id()),
                "mx": int(mx_spin.get_value()),
                "my": int(my_spin.get_value())
            }
            if el:
                el.update(new_val)
            else:
                self.label_elements.append(new_val)
            self.populate_label_model()
            self.update_previews()
        dialog.destroy()

    def on_add_label_text(self, widget):
        self.run_label_text_dialog()

    def run_label_barcode_dialog(self, el=None):
        title = "Edit Barcode" if el else "Add Barcode"
        dialog = Gtk.Dialog(title=title, transient_for=self, flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        
        grid = Gtk.Grid(row_spacing=6, column_spacing=6, margin=12)
        dialog.get_content_area().add(grid)
        
        grid.attach(Gtk.Label(label="Content:"), 0, 0, 1, 1)
        entry = Gtk.Entry()
        if el:
            entry.set_text(el.get("content", ""))
        grid.attach(entry, 1, 0, 1, 1)
        
        grid.attach(Gtk.Label(label="X:"), 0, 1, 1, 1)
        x_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=el.get("x", 40) if el else 40, lower=0, upper=2000, step_increment=10))
        grid.attach(x_spin, 1, 1, 1, 1)
        
        grid.attach(Gtk.Label(label="Y:"), 0, 2, 1, 1)
        y_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=el.get("y", 80) if el else 80, lower=0, upper=2000, step_increment=10))
        grid.attach(y_spin, 1, 2, 1, 1)
        
        grid.attach(Gtk.Label(label="Height:"), 0, 3, 1, 1)
        h_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=el.get("height", 60) if el else 60, lower=10, upper=500, step_increment=10))
        grid.attach(h_spin, 1, 3, 1, 1)
        
        grid.attach(Gtk.Label(label="Rotation:"), 0, 4, 1, 1)
        rot_combo = Gtk.ComboBoxText()
        for r in ["0", "90", "180", "270"]:
            rot_combo.append(r, f"{r}°")
        rot_combo.set_active_id(str(el.get("rotation", 0)) if el else "0")
        grid.attach(rot_combo, 1, 4, 1, 1)
        
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_val = {
                "type": "barcode",
                "content": entry.get_text(),
                "btype": "128",
                "x": int(x_spin.get_value()),
                "y": int(y_spin.get_value()),
                "height": int(h_spin.get_value()),
                "rotation": int(rot_combo.get_active_id()),
                "narrow": 2,
                "wide": 6
            }
            if el:
                el.update(new_val)
            else:
                self.label_elements.append(new_val)
            self.populate_label_model()
            self.update_previews()
        dialog.destroy()

    def on_add_label_barcode(self, widget):
        self.run_label_barcode_dialog()

    def run_label_qrcode_dialog(self, el=None):
        title = "Edit QR Code" if el else "Add QR Code"
        dialog = Gtk.Dialog(title=title, transient_for=self, flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        
        grid = Gtk.Grid(row_spacing=6, column_spacing=6, margin=12)
        dialog.get_content_area().add(grid)
        
        grid.attach(Gtk.Label(label="Content:"), 0, 0, 1, 1)
        entry = Gtk.Entry()
        if el:
            entry.set_text(el.get("content", ""))
        grid.attach(entry, 1, 0, 1, 1)
        
        grid.attach(Gtk.Label(label="X:"), 0, 1, 1, 1)
        x_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=el.get("x", 80) if el else 80, lower=0, upper=2000, step_increment=10))
        grid.attach(x_spin, 1, 1, 1, 1)
        
        grid.attach(Gtk.Label(label="Y:"), 0, 2, 1, 1)
        y_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=el.get("y", 180) if el else 180, lower=0, upper=2000, step_increment=10))
        grid.attach(y_spin, 1, 2, 1, 1)
        
        grid.attach(Gtk.Label(label="Cell Width:"), 0, 3, 1, 1)
        w_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=el.get("cell_width", 4) if el else 4, lower=1, upper=10, step_increment=1))
        grid.attach(w_spin, 1, 3, 1, 1)
        
        grid.attach(Gtk.Label(label="Rotation:"), 0, 4, 1, 1)
        rot_combo = Gtk.ComboBoxText()
        for r in ["0", "90", "180", "270"]:
            rot_combo.append(r, f"{r}°")
        rot_combo.set_active_id(str(el.get("rotation", 0)) if el else "0")
        grid.attach(rot_combo, 1, 4, 1, 1)
        
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            new_val = {
                "type": "qrcode",
                "content": entry.get_text(),
                "x": int(x_spin.get_value()),
                "y": int(y_spin.get_value()),
                "cell_width": int(w_spin.get_value()),
                "rotation": int(rot_combo.get_active_id()),
                "ecc": "M"
            }
            if el:
                el.update(new_val)
            else:
                self.label_elements.append(new_val)
            self.populate_label_model()
            self.update_previews()
        dialog.destroy()

    def on_add_label_qrcode(self, widget):
        self.run_label_qrcode_dialog()

    def run_label_image_dialog(self, el=None):
        title = "Edit Label Image" if el else "Add Label Image"
        dialog = Gtk.FileChooserDialog(title=title, transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        
        chk = Gtk.CheckButton(label="Invert Colors (Negative)")
        if el:
            chk.set_active(el.get("invert", False))
            dialog.set_filename(el.get("image", ""))
        dialog.set_extra_widget(chk)
        
        grid = Gtk.Grid(row_spacing=6, column_spacing=6, margin=6)
        dialog.get_content_area().pack_start(grid, False, False, 0)
        
        grid.attach(Gtk.Label(label="X:"), 0, 0, 1, 1)
        x_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=el.get("x", 40) if el else 40, lower=0, upper=2000, step_increment=10))
        grid.attach(x_spin, 1, 0, 1, 1)
        
        grid.attach(Gtk.Label(label="Y:"), 0, 1, 1, 1)
        y_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=el.get("y", 40) if el else 40, lower=0, upper=2000, step_increment=10))
        grid.attach(y_spin, 1, 1, 1, 1)
        
        grid.attach(Gtk.Label(label="Width:"), 0, 2, 1, 1)
        w_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=el.get("width", 200) if el else 200, lower=10, upper=1000, step_increment=10))
        grid.attach(w_spin, 1, 2, 1, 1)
        
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            if path or el:
                new_val = {
                    "type": "image",
                    "image": path if path else el["image"],
                    "x": int(x_spin.get_value()),
                    "y": int(y_spin.get_value()),
                    "width": int(w_spin.get_value()),
                    "invert": chk.get_active(),
                    "mode": 0
                }
                if el:
                    el.update(new_val)
                else:
                    self.label_elements.append(new_val)
                self.populate_label_model()
                self.update_previews()
        dialog.destroy()

    def on_add_label_img(self, widget):
        self.run_label_image_dialog()

    def on_edit_label_element(self, widget):
        selection = self.label_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            return
        idx = model.get_value(treeiter, 2)
        el = self.label_elements[idx]
        itype = el["type"]
        
        if itype == "text":
            self.run_label_text_dialog(el)
        elif itype == "barcode":
            self.run_label_barcode_dialog(el)
        elif itype == "qrcode":
            self.run_label_qrcode_dialog(el)
        elif itype == "image":
            self.run_label_image_dialog(el)

    def on_del_label_element(self, widget):
        selection = self.label_tree.get_selection()
        model, treeiter = selection.get_selected()
        if treeiter:
            idx = model.get_value(treeiter, 2)
            del self.label_elements[idx]
            self.populate_label_model()
            self.update_previews()

    def on_move_label_up(self, widget):
        selection = self.label_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            return
        idx = model.get_value(treeiter, 2)
        if idx > 0:
            self.label_elements[idx], self.label_elements[idx-1] = self.label_elements[idx-1], self.label_elements[idx]
            self.populate_label_model()
            self.update_previews()
            self.select_label_item_by_index(idx - 1)

    def on_move_label_down(self, widget):
        selection = self.label_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            return
        idx = model.get_value(treeiter, 2)
        if idx < len(self.label_elements) - 1:
            self.label_elements[idx], self.label_elements[idx+1] = self.label_elements[idx+1], self.label_elements[idx]
            self.populate_label_model()
            self.update_previews()
            self.select_label_item_by_index(idx + 1)

    def select_label_item_by_index(self, index):
        treeiter = self.label_model.get_iter_first()
        while treeiter is not None:
            if self.label_model.get_value(treeiter, 2) == index:
                self.label_tree.get_selection().select_iter(treeiter)
                path = self.label_model.get_path(treeiter)
                self.label_tree.scroll_to_cell(path, None, False, 0.0, 0.0)
                break
            treeiter = self.label_model.iter_next(treeiter)

if __name__ == "__main__":
    win = GPrinterApp()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
