from flask import Flask, Response, render_template, request, jsonify
from picamera2 import Picamera2
import io
import threading
import time
import subprocess
import os
from ap_config import setup_ap, start_ap, stop_ap, check_wifi_connection, configure_wifi
import alsaaudio
import numpy as np
import requests

app = Flask(__name__)
picam2 = Picamera2()
camera_configured = False

def generate_frames():
    global camera_configured
    if not camera_configured:
        config = picam2.create_still_configuration(main={"size": (640, 480)})
        picam2.configure(config)
        picam2.set_controls({"AwbMode": 0, "AwbEnable": 1})
        picam2.start()
        camera_configured = True
    
    try:
        while True:
            stream = io.BytesIO()
            picam2.capture_file(stream, format='jpeg')
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + stream.getvalue() + b'\r\n')
    except Exception as e:
        print(f"Error in generate_frames: {e}")
    finally:
        picam2.stop()
        camera_configured = False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/wifi_config')
def wifi_config():
    return render_template('wifi_config.html')

@app.route('/video_feed')
def video_feed():
    global camera_configured
    if camera_configured:
        picam2.stop()
        camera_configured = False
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/toggle_ap', methods=['POST'])
def toggle_ap():
    if check_wifi_connection():
        stop_ap()
        start_ap()
        time.sleep(5)  # Espera a que el AP se inicie
        return jsonify({"status": "AP started", "ip": get_ip_address()})
    else:
        stop_ap()
        time.sleep(5)  # Espera a que se intente la conexión Wi-Fi
        if check_wifi_connection():
            return jsonify({"status": "Connected to WiFi", "ip": get_ip_address()})
        else:
            start_ap()
            return jsonify({"status": "Failed to connect to WiFi, AP restarted", "ip": get_ip_address()})

@app.route('/network_status')
def network_status():
    if check_wifi_connection():
        return jsonify({"status": "Connected to WiFi", "ip": get_ip_address()})
    else:
        return jsonify({"status": "AP mode", "ip": get_ip_address()})

@app.route('/shutdown', methods=['POST'])
def shutdown():
    subprocess.call(['sudo', 'shutdown', '-h', 'now'])
    return jsonify({"status": "Shutting down..."})

@app.route('/reboot', methods=['POST'])
def reboot():
    subprocess.call(['sudo', 'reboot'])
    return jsonify({"status": "Rebooting..."})

@app.route('/configure_wifi', methods=['POST'])
def setup_wifi():
    ssid = request.form['ssid']
    password = request.form['password']
    configure_wifi(ssid, password)
    return jsonify({"status": f"Attempting to connect to {ssid}"})

def get_ip_address():
    try:
        ip = subprocess.check_output(['hostname', '-I']).decode('utf-8').strip().split()[0]
        return ip
    except:
        return "Unable to get IP"

def check_and_switch_network():
    while True:
        if not check_wifi_connection():
            print("No hay conexión Wi-Fi. Iniciando AP...")
            start_ap()
        time.sleep(60)  # Comprueba cada minuto

def initialize_network():
    print("Inicializando red...")
    if not check_wifi_connection():
        print("No se detectó conexión Wi-Fi. Iniciando AP...")
        start_ap()
    else:
        print("Conectado a Wi-Fi.")

CHUNK = 1024
CHANNELS = 1
RATE = 44100
BUFFER_SECONDS = 5
BUFFER_SIZE = RATE * BUFFER_SECONDS

audio_buffer = np.zeros(BUFFER_SIZE, dtype=np.int16)
buffer_index = 0
is_muted = False

def detect_cry(audio_data):
    # Implementa aquí tu lógica de detección de llanto
    # Este es un ejemplo simple basado en el volumen
    return np.max(np.abs(audio_data)) > 10000

def send_telegram_notification():
    bot_token = 'TU_BOT_TOKEN'
    chat_id = 'TU_CHAT_ID'
    message = 'Se ha detectado llanto del bebé!'
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    params = {'chat_id': chat_id, 'text': message}
    requests.get(url, params=params)

def audio_processor():
    global buffer_index
    inp = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, alsaaudio.PCM_NONBLOCK)
    inp.setchannels(CHANNELS)
    inp.setrate(RATE)
    inp.setformat(alsaaudio.PCM_FORMAT_S16_LE)
    inp.setperiodsize(CHUNK)

    while True:
        if not is_muted:
            l, data = inp.read()
            if l:
                audio_data = np.frombuffer(data, dtype=np.int16)
                audio_buffer[buffer_index:buffer_index+len(audio_data)] = audio_data
                buffer_index = (buffer_index + len(audio_data)) % BUFFER_SIZE
                
                if detect_cry(audio_data):
                    send_telegram_notification()
        else:
            time.sleep(0.1)

def audio_stream():
    global buffer_index
    while True:
        if not is_muted:
            start = (buffer_index - CHUNK) % BUFFER_SIZE
            end = (start + CHUNK) % BUFFER_SIZE
            if start < end:
                data = audio_buffer[start:end].tobytes()
            else:
                data = np.concatenate((audio_buffer[start:], audio_buffer[:end])).tobytes()
            yield (b'--frame\r\n'
                   b'Content-Type: audio/l16\r\n\r\n' + data + b'\r\n')
        else:
            yield (b'--frame\r\n'
                   b'Content-Type: audio/l16\r\n\r\n' + b'\x00' * CHUNK * 2 + b'\r\n')
        time.sleep(CHUNK / RATE)

@app.route('/audio_feed')
def audio_feed():
    return Response(audio_stream(),
                    mimetype='audio/l16; rate=44100; channels=1')

@app.route('/toggle_mute', methods=['POST'])
def toggle_mute():
    global is_muted
    is_muted = not is_muted
    return jsonify({"status": "Muted" if is_muted else "Unmuted"})

import atexit

def cleanup():
    global camera_configured
    if camera_configured:
        picam2.stop()
        camera_configured = False

atexit.register(cleanup)

@app.errorhandler(Exception)
def handle_exception(e):
    # Registra el error
    app.logger.error(f"Unhandled exception: {e}", exc_info=True)
    # Devuelve una respuesta de error genérica
    return jsonify(error=str(e)), 500

if __name__ == '__main__':
    setup_ap()
    initialize_network()
    network_thread = threading.Thread(target=check_and_switch_network)
    network_thread.daemon = True
    network_thread.start()
    
    audio_thread = threading.Thread(target=audio_processor)
    audio_thread.daemon = True
    audio_thread.start()
    
    app.run(host='0.0.0.0', port=8080, threaded=True)