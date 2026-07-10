import os
import glob
import subprocess
import socket
import threading
import time

def detect_printers():
    return sorted(glob.glob('/dev/usb/lp*'))

def fix_permissions(path):
    try:
        res = subprocess.run(["pkexec", "chmod", "666", path], capture_output=True)
        return res.returncode == 0
    except Exception:
        return False

def write_to_printer(path, data):
    if not os.path.exists(path):
        return False, FileNotFoundError(f"Device {path} not found.")
    try:
        with open(path, 'wb') as f:
            f.write(data)
        return True, None
    except PermissionError as e:
        if fix_permissions(path):
            try:
                with open(path, 'wb') as f:
                    f.write(data)
                return True, None
            except Exception as retry_err:
                return False, retry_err
        return False, e
    except Exception as e:
        return False, e


def query_ethernet_status(ip, port=4000):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect((ip, port))
        s.sendall(b'\x1B\x76')
        res = s.recv(16)
        s.close()
        
        if not res:
            return {
                "success": False,
                "online": False,
                "cover_open": False,
                "paper_out": False,
                "paper_near_end": False,
                "cutter_error": False,
                "error_msg": "No response from status port"
            }
            
        byte1 = res[0]
        online = not bool(byte1 & 0x08)
        cover_open = bool(byte1 & 0x20)
        paper_out = False
        paper_near_end = False
        cutter_error = False
        
        if len(res) >= 3:
            byte2 = res[1]
            cutter_error = bool(byte2 & 0x08)
            byte3 = res[2]
            paper_out = bool(byte3 & 0x60)
            paper_near_end = bool(byte3 & 0x0C)
        else:
            paper_out = bool(byte1 & 0x0C)
            paper_near_end = bool(byte1 & 0x03)
            
        error_msg = []
        if cover_open:
            error_msg.append("Cover Opened")
        if paper_out:
            error_msg.append("Out of Paper")
        if cutter_error:
            error_msg.append("Cutter Error")
        if not online:
            error_msg.append("Printer Offline")
            
        return {
            "success": True,
            "online": online,
            "cover_open": cover_open,
            "paper_out": paper_out,
            "paper_near_end": paper_near_end,
            "cutter_error": cutter_error,
            "error_msg": ", ".join(error_msg) if error_msg else "Ready"
        }
    except Exception as e:
        return {
            "success": False,
            "online": False,
            "cover_open": False,
            "paper_out": False,
            "paper_near_end": False,
            "cutter_error": False,
            "error_msg": str(e)
        }

def get_printer_model_name(ip, port=9100):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect((ip, port))
        s.sendall(b'\x1D\x49\x43')
        res = s.recv(128)
        s.close()
        
        if res:
            start_idx = 1 if res[0] in (0x3D, 0x5F) else 0
            model = res[start_idx:].split(b'\x00')[0].decode('ascii', errors='replace').strip()
            if model:
                return model
    except Exception:
        pass
        
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect((ip, port))
        s.sendall(b'~!I\r\n')
        res = s.recv(128)
        s.close()
        if res:
            model = res.split(b'\r')[0].decode('ascii', errors='replace').strip()
            if model:
                return model
    except Exception:
        pass
        
    return "GPrinter (Net)"

def send_to_ethernet_printer(ip, port, data):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((ip, port))
        s.sendall(data)
        s.close()
        return True, None
    except Exception as e:
        return False, e

def scan_lan_printers(subnet_prefix=None):
    if not subnet_prefix:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('10.255.255.255', 1))
            local_ip = s.getsockname()[0]
            s.close()
            parts = local_ip.split('.')
            if len(parts) == 4 and parts[0] != '127':
                subnet_prefix = f"{parts[0]}.{parts[1]}.{parts[2]}."
            else:
                subnet_prefix = "192.168.1."
        except Exception:
            subnet_prefix = "192.168.1."
            
    discovered = []
    lock = threading.Lock()
    threads = []
    
    def check_ip(ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            res = s.connect_ex((ip, 9100))
            s.close()
            
            if res == 0:
                name = get_printer_model_name(ip)
                with lock:
                    discovered.append((ip, name))
        except Exception:
            pass

    for i in range(1, 255):
        ip_addr = f"{subnet_prefix}{i}"
        t = threading.Thread(target=check_ip, args=(ip_addr,))
        t.start()
        threads.append(t)
        
    for t in threads:
        t.join()
        
    return sorted(discovered, key=lambda x: [int(c) for c in x[0].split('.')])

def print_with_status_check(ip, data, status_port=4000, print_port=9100):
    status = query_ethernet_status(ip, status_port)
    if not status["success"]:
        return False, f"Connection Failed: {status['error_msg']}"
        
    if status["cover_open"]:
        return False, "Print Blocked: Cover is Open"
    if status["paper_out"]:
        return False, "Print Blocked: Out of Paper"
    if not status["online"]:
        return False, "Print Blocked: Printer Offline"
        
    success, err = send_to_ethernet_printer(ip, print_port, data)
    if not success:
        return False, f"Transmission Failed: {err}"
        
    time.sleep(1.2)
    status_post = query_ethernet_status(ip, status_port)
    if status_post["success"]:
        anomaly_msg = []
        if status_post["cover_open"]:
            anomaly_msg.append("Cover Opened during print")
        if status_post["paper_out"]:
            anomaly_msg.append("Paper Ran Out during print")
        if status_post["cutter_error"]:
            anomaly_msg.append("Paper Cutter jammed")
            
        if anomaly_msg:
            return False, f"Printing Anomaly: {', '.join(anomaly_msg)}"
            
    return True, None

def get_cups_printers():
    try:
        res = subprocess.run(["lpstat", "-p"], capture_output=True, text=True)
        if res.returncode != 0:
            return []
        printers = []
        for line in res.stdout.splitlines():
            if line.startswith("printer "):
                parts = line.split()
                if len(parts) >= 2:
                    printers.append(parts[1])
        return sorted(printers)
    except Exception:
        return []

def get_default_cups_printer():
    try:
        res = subprocess.run(["lpstat", "-d"], capture_output=True, text=True)
        if res.returncode == 0:
            line = res.stdout.strip()
            if ":" in line:
                return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return None

def query_cups_status(printer_name):
    try:
        res = subprocess.run(["lpstat", "-p", printer_name], capture_output=True, text=True)
        if res.returncode == 0:
            output = res.stdout.strip()
            enabled = "enabled" in output
            status_text = "Ready" if enabled else "Disabled/Offline"
            if "disabled" in output:
                parts = output.split(" - ")
                if len(parts) > 1:
                    status_text = f"Disabled: {parts[1].strip()}"
            return {
                "success": True,
                "online": enabled,
                "error_msg": "Ready" if enabled else status_text
            }
    except Exception as e:
        return {
            "success": False,
            "online": False,
            "error_msg": str(e)
        }
    return {
        "success": False,
        "online": False,
        "error_msg": "Unknown error"
    }

def print_via_cups(printer_name, data):
    try:
        process = subprocess.Popen(
            ["lp", "-d", printer_name, "-o", "raw", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate(input=data)
        if process.returncode == 0:
            return True, None
        err_msg = stderr.decode('utf-8', errors='replace').strip()
        return False, Exception(f"lp failed with code {process.returncode}: {err_msg}")
    except Exception as e:
        return False, e

