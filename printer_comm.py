import os
import glob
import subprocess

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
