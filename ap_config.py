import subprocess
import os
import time

def is_ap_configured():
    # Verifica si el AP ya está configurado
    try:
        with open("/etc/hostapd/hostapd.conf", "r") as f:
            return "ssid=BabyMonitor" in f.read()
    except FileNotFoundError:
        return False

def setup_ap():
    if is_ap_configured():
        print("El punto de acceso ya está configurado.")
        return

    print("El punto de acceso no está configurado. Por favor, ejecute el siguiente comando con permisos de superusuario para configurarlo:")
    print("sudo python3 setup_ap.py")

def start_ap():
    subprocess.run(["sudo", "systemctl", "start", "hostapd"])
    subprocess.run(["sudo", "systemctl", "start", "dnsmasq"])

def stop_ap():
    subprocess.run(["sudo", "systemctl", "stop", "hostapd"])
    subprocess.run(["sudo", "systemctl", "stop", "dnsmasq"])

def check_wifi_connection():
    try:
        subprocess.run(["ping", "-c", "1", "8.8.8.8"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False

def configure_wifi(ssid, password):
    config = f'''
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=ES

network={{
    ssid="{ssid}"
    psk="{password}"
}}
'''
    with open('/etc/wpa_supplicant/wpa_supplicant.conf', 'w') as f:
        f.write(config)
    subprocess.call(['sudo', 'wpa_cli', '-i', 'wlan0', 'reconfigure'])
    time.sleep(10)  # Espera a que se conecte
    return check_wifi_connection()