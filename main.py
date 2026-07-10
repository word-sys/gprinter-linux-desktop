import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib

import os
import threading
import time
import socket
import fitz  # PyMuPDF
from PIL import Image

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
    .status-panel {
        font-size: 11px;
    }
""")
Gtk.StyleContext.add_provider_for_screen(
    Gdk.Screen.get_default(),
    css_provider,
    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
)

class GPrinterApp(Gtk.Window):
    def __init__(self):
        super().__init__(title="GPrinter Linux Desktop Printer")
        self.set_default_size(1050, 780)
        
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
        
        self.orders = [
            {
                "id": "ORD-100234",
                "customer": "John Doe",
                "date": "2026-07-09 09:15:00",
                "status": "Pending",
                "items": [
                    {"name": "Double Espresso", "qty": 2, "price": 2.50},
                    {"name": "Caramel Latte", "qty": 1, "price": 4.50},
                    {"name": "Butter Croissant", "qty": 1, "price": 3.00}
                ]
            },
            {
                "id": "ORD-100235",
                "customer": "Jane Smith",
                "date": "2026-07-09 09:18:00",
                "status": "Pending",
                "items": [
                    {"name": "Iced Matcha Latte", "qty": 1, "price": 5.00},
                    {"name": "Blueberry Muffin", "qty": 2, "price": 3.50}
                ]
            }
        ]
        
        self.pdf_queue = []
        
        self.status_polling_active = True
        
        self.init_ui()
        self.start_status_polling()
        self.update_previews()

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
        subtitle_lbl = Gtk.Label(label="Ethernet & Order Printing v1.0")
        subtitle_lbl.set_xalign(0.0)
        subtitle_lbl.get_style_context().add_class("dim-label")
        title_box.pack_start(title_lbl, False, False, 0)
        title_box.pack_start(subtitle_lbl, False, False, 0)
        top_bar.pack_start(title_box, False, False, 0)
        
        self.status_label = Gtk.Label()
        self.status_label.set_markup("<span foreground='orange' weight='bold'>Initializing...</span>")
        top_bar.pack_start(self.status_label, True, True, 0)
        
        print_btn = Gtk.Button(label="Print Current View")
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
        
        conn_grid.attach(Gtk.Label(label="Mode:"), 0, 0, 1, 1)
        self.conn_combo = Gtk.ComboBoxText()
        self.conn_combo.append("usb", "USB (/dev/usb/lp*)")
        self.conn_combo.append("ethernet", "Ethernet (LAN)")
        self.conn_combo.append("cups", "CUPS (System Printers)")
        self.conn_combo.set_active_id("usb")
        self.conn_combo.connect("changed", self.on_conn_mode_changed)
        conn_grid.attach(self.conn_combo, 1, 0, 1, 1)
        
        self.usb_lbl = Gtk.Label(label="Device Path:")
        conn_grid.attach(self.usb_lbl, 0, 1, 1, 1)
        self.dev_path_entry = Gtk.Entry(text="/dev/usb/lp0")
        conn_grid.attach(self.dev_path_entry, 1, 1, 1, 1)
        
        self.usb_detect_btn = Gtk.Button(label="Auto-Detect")
        self.usb_detect_btn.connect("clicked", self.on_detect_clicked)
        conn_grid.attach(self.usb_detect_btn, 1, 2, 1, 1)
        
        self.ip_lbl = Gtk.Label(label="IP Address:")
        conn_grid.attach(self.ip_lbl, 0, 3, 1, 1)
        self.ip_entry = Gtk.Entry(text="192.168.1.100")
        conn_grid.attach(self.ip_entry, 1, 3, 1, 1)
        
        self.print_port_lbl = Gtk.Label(label="Print Port:")
        conn_grid.attach(self.print_port_lbl, 0, 4, 1, 1)
        self.print_port_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=9100, lower=1, upper=65535, step_increment=1))
        conn_grid.attach(self.print_port_spin, 1, 4, 1, 1)
        
        self.status_port_lbl = Gtk.Label(label="Status Port:")
        conn_grid.attach(self.status_port_lbl, 0, 5, 1, 1)
        self.status_port_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=4000, lower=1, upper=65535, step_increment=1))
        conn_grid.attach(self.status_port_spin, 1, 5, 1, 1)
        
        self.scan_lan_btn = Gtk.Button(label="Scan LAN")
        self.scan_lan_btn.connect("clicked", self.on_scan_lan_clicked)
        conn_grid.attach(self.scan_lan_btn, 0, 6, 1, 1)
        
        self.discovered_combo = Gtk.ComboBoxText()
        self.discovered_combo.connect("changed", self.on_discovered_changed)
        conn_grid.attach(self.discovered_combo, 1, 6, 1, 1)
        
        self.cups_lbl = Gtk.Label(label="CUPS Printer:")
        conn_grid.attach(self.cups_lbl, 0, 8, 1, 1)
        self.cups_combo = Gtk.ComboBoxText()
        conn_grid.attach(self.cups_combo, 1, 8, 1, 1)
        
        self.cups_refresh_btn = Gtk.Button(label="Refresh CUPS List")
        self.cups_refresh_btn.connect("clicked", self.on_refresh_cups_clicked)
        conn_grid.attach(self.cups_refresh_btn, 1, 9, 1, 1)
        
        test_btn = Gtk.Button(label="Test Connection")
        test_btn.connect("clicked", self.on_test_clicked)
        conn_grid.attach(test_btn, 0, 7, 2, 1)
        
        config_frame = Gtk.Frame(label="General Print Settings")
        sidebar.pack_start(config_frame, False, False, 0)
        
        config_grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        config_frame.add(config_grid)
        
        config_grid.attach(Gtk.Label(label="Density/Width:"), 0, 0, 1, 1)
        self.width_combo = Gtk.ComboBoxText()
        self.width_combo.append("384", "2 inch (384 dots)")
        self.width_combo.append("576", "80mm / 3.14 inch (576 dots)")
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
        
        self.autocut_chk = Gtk.CheckButton(label="Auto-Cut Paper after print")
        self.autocut_chk.set_active(True)
        config_grid.attach(self.autocut_chk, 0, 3, 2, 1)
        
        self.on_conn_mode_changed(self.conn_combo)
        
        self.notebook = Gtk.Notebook()
        main_hbox.pack_start(self.notebook, True, True, 6)
        
        self.setup_order_tab()
        self.setup_receipt_tab()
        self.setup_label_tab()
        self.setup_pdf_tab()

    def on_conn_mode_changed(self, widget):
        mode = widget.get_active_id()
        is_usb = (mode == "usb")
        is_ethernet = (mode == "ethernet")
        is_cups = (mode == "cups")
        
        self.usb_lbl.set_visible(is_usb)
        self.dev_path_entry.set_visible(is_usb)
        self.usb_detect_btn.set_visible(is_usb)
        
        self.ip_lbl.set_visible(is_ethernet)
        self.ip_entry.set_visible(is_ethernet)
        self.print_port_lbl.set_visible(is_ethernet)
        self.print_port_spin.set_visible(is_ethernet)
        self.status_port_lbl.set_visible(is_ethernet)
        self.status_port_spin.set_visible(is_ethernet)
        self.scan_lan_btn.set_visible(is_ethernet)
        self.discovered_combo.set_visible(is_ethernet)
        
        self.cups_lbl.set_visible(is_cups)
        self.cups_combo.set_visible(is_cups)
        self.cups_refresh_btn.set_visible(is_cups)
        
        if is_cups:
            self.refresh_cups_list()

    def refresh_cups_list(self):
        self.cups_combo.remove_all()
        printers = printer_comm.get_cups_printers()
        default = printer_comm.get_default_cups_printer()
        for p in printers:
            self.cups_combo.append(p, p)
        if default and default in printers:
            self.cups_combo.set_active_id(default)
        elif printers:
            self.cups_combo.set_active(0)

    def on_refresh_cups_clicked(self, widget):
        self.refresh_cups_list()

    def start_status_polling(self):
        GLib.timeout_add(1500, self.poll_printer_status)

    def poll_printer_status(self):
        if not self.status_polling_active:
            return True
            
        mode = self.conn_combo.get_active_id()
        if mode == "usb":
            path = self.dev_path_entry.get_text()
            if os.path.exists(path):
                self.status_label.set_markup("<span foreground='#2e7d32' weight='bold'>Connected (USB)</span>")
            else:
                self.status_label.set_markup("<span foreground='#c62828' weight='bold'>Disconnected (USB)</span>")
        elif mode == "cups":
            printer_name = self.cups_combo.get_active_id()
            if not printer_name:
                self.status_label.set_markup("<span foreground='#c62828' weight='bold'>No CUPS printer</span>")
                return True
                
            def run_query():
                status = printer_comm.query_cups_status(printer_name)
                GLib.idle_add(self.update_cups_status_ui, status, printer_name)
                
            threading.Thread(target=run_query, daemon=True).start()
        else:
            ip = self.ip_entry.get_text()
            try:
                status_port = int(self.status_port_spin.get_value())
            except Exception:
                status_port = 4000
                
            def run_query():
                status = printer_comm.query_ethernet_status(ip, status_port)
                GLib.idle_add(self.update_ethernet_status_ui, status)
                
            threading.Thread(target=run_query, daemon=True).start()
            
        return True

    def update_cups_status_ui(self, status, printer_name):
        if not status["success"] or not status["online"]:
            self.status_label.set_markup(f"<span foreground='#c62828' weight='bold'>CUPS Offline ({printer_name}): {status['error_msg']}</span>")
        else:
            self.status_label.set_markup(f"<span foreground='#2e7d32' weight='bold'>CUPS Ready ({printer_name})</span>")


    def update_ethernet_status_ui(self, status):
        if not status["success"]:
            self.status_label.set_markup(f"<span foreground='#c62828' weight='bold'>Offline: {status['error_msg']}</span>")
        else:
            msg = status["error_msg"]
            if msg == "Ready":
                self.status_label.set_markup(f"<span foreground='#2e7d32' weight='bold'>Printer Ready ({self.ip_entry.get_text()})</span>")
            else:
                self.status_label.set_markup(f"<span foreground='#ef6c00' weight='bold'>Printer Alert: {msg}</span>")

    def on_scan_lan_clicked(self, widget):
        self.status_label.set_text("Scanning LAN subnets...")
        widget.set_sensitive(False)
        
        def run_scan():
            printers = printer_comm.scan_lan_printers()
            GLib.idle_add(self.update_discovered_printers, printers, widget)
            
        threading.Thread(target=run_scan, daemon=True).start()

    def update_discovered_printers(self, printers, button):
        button.set_sensitive(True)
        self.discovered_combo.clear()
        
        if not printers:
            self.status_label.set_text("No LAN printers found")
            self.show_info_dialog("No printers discovered on local network.")
            return
            
        self.status_label.set_text(f"Scan complete: found {len(printers)} printers")
        for ip, model in printers:
            self.discovered_combo.append(ip, f"{model} ({ip})")
        self.discovered_combo.set_active(0)

    def on_discovered_changed(self, widget):
        ip = widget.get_active_id()
        if ip:
            self.ip_entry.set_text(ip)

    def setup_order_tab(self):
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_margin_bottom(10)
        hbox.set_margin_start(10)
        hbox.set_margin_end(10)
        
        self.notebook.append_page(hbox, Gtk.Label(label="Order List"))
        
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left_box.set_size_request(350, -1)
        left_box.set_margin_top(36)
        hbox.pack_start(left_box, False, False, 6)
        
        scroll = Gtk.ScrolledWindow()
        left_box.pack_start(scroll, True, True, 0)
        
        self.order_model = Gtk.ListStore(str, str, str, str, int)
        self.order_tree = Gtk.TreeView(model=self.order_model)
        self.order_tree.connect("cursor-changed", self.on_order_selected)
        scroll.add(self.order_tree)
        
        self.order_tree.append_column(Gtk.TreeViewColumn("Order ID", Gtk.CellRendererText(), text=0))
        self.order_tree.append_column(Gtk.TreeViewColumn("Customer", Gtk.CellRendererText(), text=1))
        self.order_tree.append_column(Gtk.TreeViewColumn("Total", Gtk.CellRendererText(), text=2))
        self.order_tree.append_column(Gtk.TreeViewColumn("Status", Gtk.CellRendererText(), text=3))
        
        self.populate_order_model()
        
        btn_box = Gtk.Grid(row_spacing=4, column_spacing=4)
        left_box.pack_start(btn_box, False, False, 0)
        
        add_btn = Gtk.Button(label="Add Order")
        add_btn.connect("clicked", self.on_add_order_clicked)
        btn_box.attach(add_btn, 0, 0, 1, 1)
        
        edit_btn = Gtk.Button(label="Edit Order")
        edit_btn.connect("clicked", self.on_edit_order_clicked)
        btn_box.attach(edit_btn, 1, 0, 1, 1)
        
        del_btn = Gtk.Button(label="Delete Order")
        del_btn.get_style_context().add_class("destructive-action")
        del_btn.connect("clicked", self.on_del_order_clicked)
        btn_box.attach(del_btn, 2, 0, 1, 1)
        
        print_order_btn = Gtk.Button(label="Print Selected Order")
        print_order_btn.get_style_context().add_class("suggested-action")
        print_order_btn.connect("clicked", self.on_print_order_clicked)
        btn_box.attach(print_order_btn, 0, 1, 3, 1)
        
        right_scroll = Gtk.ScrolledWindow()
        right_scroll.set_margin_top(36)
        hbox.pack_start(right_scroll, True, True, 6)
        
        self.order_preview = PrinterPreviewCanvas()
        right_scroll.add(self.order_preview)

    def populate_order_model(self):
        self.order_model.clear()
        for idx, order in enumerate(self.orders):
            subtotal = sum(it["qty"] * it["price"] for it in order["items"])
            total = subtotal * 1.08
            self.order_model.append([
                order["id"],
                order["customer"],
                f"${total:.2f}",
                order["status"],
                idx
            ])

    def on_order_selected(self, widget):
        selection = self.order_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            return
        idx = model.get_value(treeiter, 4)
        order = self.orders[idx]
        items = self.compile_order_to_receipt_items(order)
        
        w_id = self.width_combo.get_active_id()
        tw = int(w_id) if w_id else 832
        self.order_preview.set_receipt_items(items, tw, self.chars_per_line, self.left_margin)

    def generate_mock_qrcode(self, data):
        size = 25
        cell = 6
        img = Image.new('1', (size * cell, size * cell), 1)
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        
        def draw_finder(x, y):
            draw.rectangle([x*cell, y*cell, (x+7)*cell - 1, (y+7)*cell - 1], fill=0)
            draw.rectangle([(x+1)*cell, (y+1)*cell, (x+6)*cell - 1, (y+6)*cell - 1], fill=1)
            draw.rectangle([(x+2)*cell, (y+2)*cell, (x+5)*cell - 1, (y+5)*cell - 1], fill=0)
            
        draw_finder(0, 0)
        draw_finder(18, 0)
        draw_finder(0, 18)
        
        import random
        rng = random.Random(hash(data))
        for r in range(size):
            for c in range(size):
                if (r < 8 and c < 8) or (r < 8 and c > 16) or (r > 16 and c < 8):
                    continue
                if rng.random() > 0.5:
                    draw.rectangle([c*cell, r*cell, (c+1)*cell - 1, (r+1)*cell - 1], fill=0)
        return img

    def compile_order_to_receipt_items(self, order):
        items = []
        items.append({"type": "text", "text": "GPRINTER ORDER INVOICE", "align": "center", "bold": True, "double_width": True, "double_height": True})
        items.append({"type": "text", "text": "Ethernet Print Service", "align": "center", "bold": False})
        items.append({"type": "separator"})
        items.append({"type": "text", "text": f"Order: {order['id']}", "align": "left", "bold": True})
        items.append({"type": "text", "text": f"Customer: {order['customer']}", "align": "left"})
        items.append({"type": "text", "text": f"Date: {order['date']}", "align": "left"})
        items.append({"type": "separator"})
        
        subtotal = 0.0
        for it in order["items"]:
            name_qty = f"{it['name']} x{it['qty']}"
            price_total = f"${(it['price'] * it['qty']):.2f}"
            items.append({
                "type": "text",
                "text": name_qty,
                "right_text": price_total,
                "bold": False
            })
            subtotal += it['price'] * it['qty']
            
        tax = subtotal * 0.08
        total = subtotal + tax
        
        items.append({"type": "separator"})
        items.append({"type": "text", "text": "Subtotal", "right_text": f"${subtotal:.2f}"})
        items.append({"type": "text", "text": "Tax (8%)", "right_text": f"${tax:.2f}"})
        items.append({"type": "text", "text": "Total", "right_text": f"${total:.2f}", "bold": True, "double_height": True})
        items.append({"type": "separator"})
        
        qr_img = self.generate_mock_qrcode(f"https://gprinter.com/verify/{order['id']}")
        items.append({"type": "image", "image": qr_img, "align": "center", "keep_aspect": True, "width": 180})
        
        items.append({"type": "feed", "lines": 3})
        return items

    def on_add_order_clicked(self, widget):
        dialog = Gtk.Dialog(title="Add New Order", transient_for=self, flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        
        grid = Gtk.Grid(row_spacing=6, column_spacing=6, margin=12)
        dialog.get_content_area().add(grid)
        
        grid.attach(Gtk.Label(label="Order ID:"), 0, 0, 1, 1)
        id_entry = Gtk.Entry(text=f"ORD-{int(time.time()) % 1000000:06d}")
        grid.attach(id_entry, 1, 0, 1, 1)
        
        grid.attach(Gtk.Label(label="Customer:"), 0, 1, 1, 1)
        cust_entry = Gtk.Entry(text="John Doe")
        grid.attach(cust_entry, 1, 1, 1, 1)
        
        grid.attach(Gtk.Label(label="Item Details (Name, qty, price):"), 0, 2, 2, 1)
        
        grid.attach(Gtk.Label(label="Item A (Qty):"), 0, 3, 1, 1)
        qty_a = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=1, lower=0, upper=10, step_increment=1))
        grid.attach(qty_a, 1, 3, 1, 1)
        
        grid.attach(Gtk.Label(label="Item B (Qty):"), 0, 4, 1, 1)
        qty_b = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=0, lower=0, upper=10, step_increment=1))
        grid.attach(qty_b, 1, 4, 1, 1)
        
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            items = []
            if qty_a.get_value_as_int() > 0:
                items.append({"name": "Black Coffee", "qty": qty_a.get_value_as_int(), "price": 3.00})
            if qty_b.get_value_as_int() > 0:
                items.append({"name": "Cheese Cake", "qty": qty_b.get_value_as_int(), "price": 4.50})
                
            if not items:
                items.append({"name": "Generic Item", "qty": 1, "price": 10.00})
                
            new_order = {
                "id": id_entry.get_text(),
                "customer": cust_entry.get_text(),
                "date": time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "Pending",
                "items": items
            }
            self.orders.append(new_order)
            self.populate_order_model()
        dialog.destroy()

    def on_edit_order_clicked(self, widget):
        selection = self.order_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            self.show_error_dialog("No order selected.")
            return
        idx = model.get_value(treeiter, 4)
        order = self.orders[idx]
        
        dialog = Gtk.Dialog(title="Edit Customer", transient_for=self, flags=0)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
        
        grid = Gtk.Grid(row_spacing=6, column_spacing=6, margin=12)
        dialog.get_content_area().add(grid)
        
        grid.attach(Gtk.Label(label="Customer Name:"), 0, 0, 1, 1)
        cust_entry = Gtk.Entry(text=order["customer"])
        grid.attach(cust_entry, 1, 0, 1, 1)
        
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            order["customer"] = cust_entry.get_text()
            self.populate_order_model()
            self.on_order_selected(None)
        dialog.destroy()

    def on_del_order_clicked(self, widget):
        selection = self.order_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            return
        idx = model.get_value(treeiter, 4)
        del self.orders[idx]
        self.populate_order_model()
        self.order_preview.set_receipt_items([], 832)

    def on_print_order_clicked(self, widget):
        selection = self.order_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            self.show_error_dialog("No order selected.")
            return
            
        idx = model.get_value(treeiter, 4)
        order = self.orders[idx]
        
        w_id = self.width_combo.get_active_id()
        tw = int(w_id) if w_id else 832
        
        items = self.compile_order_to_receipt_items(order)
        data = escpos_gen.compile_receipt(items, tw, self.chars_per_line, self.left_margin)
        
        if self.autocut_chk.get_active():
            data += b'\x1D\x56\x42\x00'
            
        mode = self.conn_combo.get_active_id()
        if mode == "usb":
            path = self.dev_path_entry.get_text()
            self.status_label.set_text("Printing order via USB...")
            success, err = printer_comm.write_to_printer(path, data)
            if success:
                self.status_label.set_text("Print succeeded")
                order["status"] = "Printed"
                self.populate_order_model()
            else:
                self.status_label.set_text("Print failed")
                order["status"] = "Error"
                self.populate_order_model()
                self.show_error_dialog(f"Printing failed: {err}")
        elif mode == "cups":
            printer_name = self.cups_combo.get_active_id()
            if not printer_name:
                self.show_error_dialog("No CUPS printer selected.")
                return
            self.status_label.set_text("Printing order via CUPS...")
            def run_print():
                success, err = printer_comm.print_via_cups(printer_name, data)
                if success:
                    GLib.idle_add(self.order_print_completed, order, idx, True, None)
                else:
                    GLib.idle_add(self.order_print_completed, order, idx, False, err)
            threading.Thread(target=run_print, daemon=True).start()
        else:
            ip = self.ip_entry.get_text()
            try:
                status_port = int(self.status_port_spin.get_value())
                print_port = int(self.print_port_spin.get_value())
            except Exception:
                status_port = 4000
                print_port = 9100
                
            self.status_label.set_text("Printing LAN order (status checked)...")
            
            def run_print():
                success, err = printer_comm.print_with_status_check(ip, data, status_port, print_port)
                if success:
                    GLib.idle_add(self.order_print_completed, order, idx, True, None)
                else:
                    GLib.idle_add(self.order_print_completed, order, idx, False, err)
                    
            threading.Thread(target=run_print, daemon=True).start()

    def order_print_completed(self, order, idx, success, err):
        if success:
            self.status_label.set_text("Print succeeded")
            order["status"] = "Printed"
            self.populate_order_model()
            self.show_info_dialog("Order printed successfully!")
        else:
            self.status_label.set_text("Print failed")
            order["status"] = f"Error: {err}"
            self.populate_order_model()
            self.show_error_dialog(f"Printing failed:\n{err}")

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
        
        import_btn = Gtk.Button(label="Import .bin")
        import_btn.connect("clicked", self.on_import_receipt_bin)
        btn_box.attach(import_btn, 0, 3, 2, 1)
        
        export_btn = Gtk.Button(label="Export .bin")
        export_btn.connect("clicked", self.on_export_receipt_bin)
        btn_box.attach(export_btn, 2, 3, 2, 1)
        
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

    def on_import_receipt_bin(self, widget):
        dialog = Gtk.FileChooserDialog(title="Import Raw ESC/POS Binary", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        
        filter_bin = Gtk.FileFilter()
        filter_bin.set_name("Binary files (*.bin)")
        filter_bin.add_pattern("*.bin")
        dialog.add_filter(filter_bin)
        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            if path:
                try:
                    with open(path, 'rb') as f:
                        data = f.read()
                    parsed = escpos_gen.parse_receipt(data)
                    if parsed:
                        self.receipt_items = parsed
                        self.populate_receipt_model()
                        self.update_previews()
                    else:
                        self.show_error_dialog("Failed to parse or empty ESC/POS binary file.")
                except Exception as e:
                    self.show_error_dialog(f"Import failed: {e}")
        dialog.destroy()

    def on_export_receipt_bin(self, widget):
        dialog = Gtk.FileChooserDialog(title="Export Raw ESC/POS Binary", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        dialog.set_current_name("receipt.bin")
        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            if path:
                try:
                    w_id = self.width_combo.get_active_id()
                    tw = int(w_id) if w_id else 832
                    data = escpos_gen.compile_receipt(self.receipt_items, tw, self.chars_per_line, self.left_margin)
                    if self.autocut_chk.get_active():
                        data += b'\x1D\x56\x42\x00'
                    with open(path, 'wb') as f:
                        f.write(data)
                except Exception as e:
                    self.show_error_dialog(f"Export failed: {e}")
        dialog.destroy()

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
        
        import_btn = Gtk.Button(label="Import .bin")
        import_btn.connect("clicked", self.on_import_label_bin)
        btn_box.attach(import_btn, 0, 3, 2, 1)
        
        export_btn = Gtk.Button(label="Export .bin")
        export_btn.connect("clicked", self.on_export_label_bin)
        btn_box.attach(export_btn, 2, 3, 2, 1)
        
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

    def on_import_label_bin(self, widget):
        dialog = Gtk.FileChooserDialog(title="Import Raw TSPL Binary", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        
        filter_bin = Gtk.FileFilter()
        filter_bin.set_name("Binary files (*.bin)")
        filter_bin.add_pattern("*.bin")
        dialog.add_filter(filter_bin)
        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            if path:
                try:
                    with open(path, 'rb') as f:
                        data = f.read()
                    w_mm, h_mm, g_mm, elements = tspl_gen.parse_label(data)
                    self.label_width_mm = w_mm
                    self.label_height_mm = h_mm
                    self.label_gap_mm = g_mm
                    self.label_elements = elements
                    
                    self.lbl_w_entry.set_text(str(w_mm))
                    self.lbl_h_entry.set_text(str(h_mm))
                    self.lbl_g_entry.set_text(str(g_mm))
                    
                    self.populate_label_model()
                    self.update_previews()
                except Exception as e:
                    self.show_error_dialog(f"Import failed: {e}")
        dialog.destroy()

    def on_export_label_bin(self, widget):
        dialog = Gtk.FileChooserDialog(title="Export Raw TSPL Binary", transient_for=self, action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        dialog.set_current_name("label.bin")
        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            if path:
                try:
                    data = tspl_gen.compile_label(self.label_width_mm, self.label_height_mm, self.label_gap_mm, self.label_elements)
                    if self.autocut_chk.get_active():
                        data += b"CUT\r\n"
                    with open(path, 'wb') as f:
                        f.write(data)
                except Exception as e:
                    self.show_error_dialog(f"Export failed: {e}")
        dialog.destroy()

    def setup_pdf_tab(self):
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        hbox.set_margin_bottom(10)
        hbox.set_margin_start(10)
        hbox.set_margin_end(10)
        self.notebook.append_page(hbox, Gtk.Label(label="Quick PDF"))
        
        left_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        left_box.set_size_request(320, -1)
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
        
        queue_frame = Gtk.Frame(label="PDF Print Queue (Multiple PDFs)")
        left_box.pack_start(queue_frame, True, True, 0)
        
        q_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        queue_frame.add(q_vbox)
        
        q_scroll = Gtk.ScrolledWindow()
        q_scroll.set_size_request(-1, 150)
        q_vbox.pack_start(q_scroll, True, True, 0)
        
        # Cols: Filename, Range, Status, internal index
        self.pdf_queue_model = Gtk.ListStore(str, str, str, int)
        self.pdf_queue_tree = Gtk.TreeView(model=self.pdf_queue_model)
        self.pdf_queue_tree.connect("cursor-changed", self.on_queue_item_selected)
        q_scroll.add(self.pdf_queue_tree)
        self.pdf_queue_tree.append_column(Gtk.TreeViewColumn("File Name", Gtk.CellRendererText(), text=0))
        self.pdf_queue_tree.append_column(Gtk.TreeViewColumn("Pages", Gtk.CellRendererText(), text=1))
        self.pdf_queue_tree.append_column(Gtk.TreeViewColumn("Status", Gtk.CellRendererText(), text=2))
        
        q_btn_grid = Gtk.Grid(row_spacing=2, column_spacing=2)
        q_vbox.pack_start(q_btn_grid, False, False, 0)
        
        q_add_btn = Gtk.Button(label="+ Add PDF")
        q_add_btn.connect("clicked", self.on_add_pdf_to_queue)
        q_btn_grid.attach(q_add_btn, 0, 0, 1, 1)
        
        q_rem_btn = Gtk.Button(label="- Remove")
        q_rem_btn.connect("clicked", self.on_remove_pdf_from_queue)
        q_btn_grid.attach(q_rem_btn, 1, 0, 1, 1)
        
        q_clear_btn = Gtk.Button(label="Clear")
        q_clear_btn.connect("clicked", self.on_clear_pdf_queue)
        q_btn_grid.attach(q_clear_btn, 2, 0, 1, 1)
        
        q_print_btn = Gtk.Button(label="Print Queue")
        q_print_btn.get_style_context().add_class("suggested-action")
        q_print_btn.connect("clicked", self.on_print_pdf_queue_clicked)
        q_btn_grid.attach(q_print_btn, 0, 1, 3, 1)
        
        right_scroll = Gtk.ScrolledWindow()
        right_scroll.set_margin_top(36)
        hbox.pack_start(right_scroll, True, True, 6)
        
        self.pdf_preview = PrinterPreviewCanvas()
        right_scroll.add(self.pdf_preview)

    def populate_pdf_queue_model(self):
        self.pdf_queue_model.clear()
        for idx, item in enumerate(self.pdf_queue):
            filename = os.path.basename(item["path"])
            self.pdf_queue_model.append([filename, item["range"], item["status"], idx])

    def on_add_pdf_to_queue(self, widget):
        dialog = Gtk.FileChooserDialog(title="Select PDF for Queue", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        
        filter_pdf = Gtk.FileFilter()
        filter_pdf.set_name("PDF Files (*.pdf)")
        filter_pdf.add_pattern("*.pdf")
        dialog.add_filter(filter_pdf)
        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            dialog.destroy()
            if path:
                # Page Range dialog
                range_dlg = Gtk.Dialog(title="Select Page Range", transient_for=self, flags=0)
                range_dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK)
                grid = Gtk.Grid(row_spacing=6, column_spacing=6, margin=12)
                range_dlg.get_content_area().add(grid)
                grid.attach(Gtk.Label(label="Range (e.g. '0-1' for 2 pages, 'All', or '0,1'):"), 0, 0, 2, 1)
                entry = Gtk.Entry(text="0-1")
                grid.attach(entry, 0, 1, 2, 1)
                
                range_dlg.show_all()
                resp = range_dlg.run()
                if resp == Gtk.ResponseType.OK:
                    self.pdf_queue.append({
                        "path": path,
                        "range": entry.get_text(),
                        "status": "Pending"
                    })
                    self.populate_pdf_queue_model()
                range_dlg.destroy()
        else:
            dialog.destroy()

    def on_remove_pdf_from_queue(self, widget):
        selection = self.pdf_queue_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            return
        idx = model.get_value(treeiter, 3)
        del self.pdf_queue[idx]
        self.populate_pdf_queue_model()

    def on_clear_pdf_queue(self, widget):
        self.pdf_queue.clear()
        self.populate_pdf_queue_model()

    def on_queue_item_selected(self, widget):
        selection = self.pdf_queue_tree.get_selection()
        model, treeiter = selection.get_selected()
        if not treeiter:
            return
        idx = model.get_value(treeiter, 3)
        path = self.pdf_queue[idx]["path"]
        try:
            self.current_pdf_doc = fitz.open(path)
            self.page_spin.set_range(0, len(self.current_pdf_doc) - 1)
            self.page_spin.set_value(0)
            self.current_pdf_page = 0
            self.update_pdf_preview()
        except Exception:
            pass

    def on_print_pdf_queue_clicked(self, widget):
        if not self.pdf_queue:
            self.show_error_dialog("The PDF print queue is empty.")
            return
            
        mode = self.conn_combo.get_active_id()
        cups_printer = self.cups_combo.get_active_id() if mode == "cups" else None
        w_id = self.width_combo.get_active_id()
        tw = int(w_id) if w_id else 832
        
        jobs = []
        for item in self.pdf_queue:
            jobs.append({
                "path": item["path"],
                "range": item["range"],
                "item": item
            })
            
        self.status_label.set_text("Printing PDF queue...")
        
        def run_queue_print():
            for job in jobs:
                q_item = job["item"]
                GLib.idle_add(self.update_pdf_status_in_loop, q_item, "Printing...")
                try:
                    doc = fitz.open(job["path"])
                    pages = []
                    r_str = job["range"].strip().lower()
                    if r_str == "all":
                        pages = list(range(len(doc)))
                    elif "-" in r_str:
                        parts = r_str.split("-")
                        pages = list(range(int(parts[0]), min(int(parts[1]) + 1, len(doc))))
                    else:
                        parts = r_str.split(",")
                        for p in parts:
                            if p.strip().isdigit():
                                pages.append(int(p.strip()))
                                
                    items = []
                    for p_num in pages:
                        if p_num < len(doc):
                            page = doc.load_page(p_num)
                            pix = page.get_pixmap(dpi=200)
                            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                            items.append({"type": "image", "image": img, "invert": self.pdf_invert})
                            
                    if not items:
                        GLib.idle_add(self.update_pdf_status_in_loop, q_item, "Empty range")
                        continue
                        
                    data = escpos_gen.compile_receipt(items, tw, self.chars_per_line, self.left_margin)
                    if self.autocut_chk.get_active():
                        data += b'\x1D\x56\x42\x00'
                        
                    if mode == "usb":
                        path = self.dev_path_entry.get_text()
                        success, err = printer_comm.write_to_printer(path, data)
                    elif mode == "cups":
                        if not cups_printer:
                            success, err = False, "No CUPS printer selected"
                        else:
                            success, err = printer_comm.print_via_cups(cups_printer, data)
                    else:
                        ip = self.ip_entry.get_text()
                        try:
                            status_port = int(self.status_port_spin.get_value())
                            print_port = int(self.print_port_spin.get_value())
                        except Exception:
                            status_port = 4000
                            print_port = 9100
                        success, err = printer_comm.print_with_status_check(ip, data, status_port, print_port)
                        
                    if success:
                        GLib.idle_add(self.update_pdf_status_in_loop, q_item, "Printed")
                    else:
                        GLib.idle_add(self.update_pdf_status_in_loop, q_item, f"Error: {err}")
                        GLib.idle_add(self.show_error_dialog_from_thread, f"PDF printing failed: {err}")
                        break
                except Exception as e:
                    GLib.idle_add(self.update_pdf_status_in_loop, q_item, f"Failed: {e}")
                    GLib.idle_add(self.show_error_dialog_from_thread, f"PDF load exception: {e}")
                    break
            GLib.idle_add(self.status_label.set_text, "Queue finished")
            
        threading.Thread(target=run_queue_print, daemon=True).start()

    def update_pdf_status_in_loop(self, q_item, status):
        q_item["status"] = status
        self.populate_pdf_queue_model()

    def show_error_dialog_from_thread(self, text):
        self.show_error_dialog(text)

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
            if self.autocut_chk.get_active():
                data += b'\x1D\x56\x42\x00'
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
            self.status_label.set_markup(f"<span foreground='#2e7d32' weight='bold'>Detected: {printers[0]}</span>")
        else:
            self.status_label.set_markup("<span foreground='#c62828' weight='bold'>No USB printer detected</span>")
            self.show_error_dialog("No GPrinter USB printer detected.")

    def on_test_clicked(self, widget):
        test_bytes = escpos_gen.ESC_INIT + escpos_gen.ALIGN_CENTER + b"Connection Test OK\n" + escpos_gen.get_feed_command(4)
        if self.autocut_chk.get_active():
            test_bytes += b'\x1D\x56\x42\x00'
        self.send_to_printer(test_bytes)

    def send_to_printer(self, data):
        mode = self.conn_combo.get_active_id()
        if mode == "usb":
            path = self.dev_path_entry.get_text()
            self.status_label.set_text("Printing USB...")
            success, err = printer_comm.write_to_printer(path, data)
            if success:
                self.status_label.set_text("Print succeeded")
            else:
                self.status_label.set_text("Print failed")
                self.show_error_dialog(f"Printing failed: {err}")
        elif mode == "cups":
            printer_name = self.cups_combo.get_active_id()
            if not printer_name:
                self.show_error_dialog("No CUPS printer selected.")
                return
            self.status_label.set_text("Printing CUPS...")
            def run_send():
                success, err = printer_comm.print_via_cups(printer_name, data)
                if success:
                    GLib.idle_add(self.status_label.set_markup, "<span foreground='#2e7d32' weight='bold'>Print Succeeded</span>")
                else:
                    GLib.idle_add(self.status_label.set_markup, "<span foreground='#c62828' weight='bold'>Print Failed</span>")
                    GLib.idle_add(self.show_error_dialog_from_thread, f"Printing failed: {err}")
            threading.Thread(target=run_send, daemon=True).start()
        else:
            ip = self.ip_entry.get_text()
            try:
                status_port = int(self.status_port_spin.get_value())
                print_port = int(self.print_port_spin.get_value())
            except Exception:
                status_port = 4000
                print_port = 9100
                
            self.status_label.set_text("Printing Ethernet...")
            
            def run_send():
                success, err = printer_comm.print_with_status_check(ip, data, status_port, print_port)
                if success:
                    GLib.idle_add(self.status_label.set_markup, "<span foreground='#2e7d32' weight='bold'>Print Succeeded</span>")
                else:
                    GLib.idle_add(self.status_label.set_markup, "<span foreground='#c62828' weight='bold'>Print Failed</span>")
                    GLib.idle_add(self.show_error_dialog_from_thread, f"Printing failed: {err}")
            threading.Thread(target=run_send, daemon=True).start()

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
            self.on_print_order_clicked(None)
        elif page == 1:
            data = escpos_gen.compile_receipt(self.receipt_items, tw, self.chars_per_line, self.left_margin)
            if self.autocut_chk.get_active():
                data += b'\x1D\x56\x42\x00'
            self.send_to_printer(data)
        elif page == 2:
            data = tspl_gen.compile_label(self.label_width_mm, self.label_height_mm, self.label_gap_mm, self.label_elements)
            if self.autocut_chk.get_active():
                data += b"CUT\r\n"
            self.send_to_printer(data)
        elif page == 3:
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

    def show_info_dialog(self, message):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Information"
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

if __name__ == "__main__":
    win = GPrinterApp()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
