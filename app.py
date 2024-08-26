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
from pydub import AudioSegment

app = Flask(__name__)
picam2 = Picamera2()

def generate_frames():
    config = picam2.create_still_configuration(main={"size": (640, 480)})
    picam2.configure(config)

    # Ajustar el balance de blancos
    picam2.set_controls({"AwbMode": 0})  # 0 es el modo automático
    picam2.set_controls({"AwbEnable": 1})  # Habilitar el balance de blancos automático

    picam2.start()
    
    try:
        while True:
            stream = io.BytesIO()
            picam2.capture_file(stream, format='jpeg')
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + stream.getvalue() + b'\r\n')
    finally:
        picam2.stop()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/wifi_config')
def wifi_config():
    return render_template('wifi_config.html')

@app.route('/video_feed')
def video_feed():
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
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

audio = pyaudio.PyAudio()
stream = None
is_muted = False

def get_input_device_index():
    p = pyaudio.PyAudio()
    info = p.get_host_api_info_by_index(0)
    numdevices = info.get('deviceCount')
    for i in range(0, numdevices):
        if (p.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels')) > 0:
            print("Input Device id ", i, " - ", p.get_device_info_by_host_api_device_index(0, i).get('name'))
    p.terminate()
    return 0  # Usar el índice 0 por defecto

DEVICE_INDEX = get_input_device_index()

def audio_stream():
    try:
        inp = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, alsaaudio.PCM_NONBLOCK)
        inp.setchannels(CHANNELS)
        inp.setrate(RATE)
        inp.setformat(alsaaudio.PCM_FORMAT_S16_LE)
        inp.setperiodsize(CHUNK)
        print("ALSA audio stream opened successfully")
    except Exception as e:
        print(f"Error opening ALSA audio stream: {e}")
        return

    while True:
        if not is_muted:
            try:
                l, data = inp.read()
                if l:
                    try:
                        audio_segment = AudioSegment(
                            data=data,
                            sample_width=2,
                            frame_rate=RATE,
                            channels=CHANNELS
                        )
                        buf = io.BytesIO()
                        audio_segment.export(buf, format="mp3")
                        yield (b'--frame\r\n'
                               b'Content-Type: audio/mpeg\r\n\r\n' + buf.getvalue() + b'\r\n')
                    except Exception as e:
                        print(f"Error processing audio: {e}")
                        yield (b'--frame\r\n'
                               b'Content-Type: audio/mpeg\r\n\r\n' + b'\x00' * CHUNK + b'\r\n')
            except IOError as e:
                print(f"Error de E/S: {e}")
                yield (b'--frame\r\n'
                       b'Content-Type: audio/mpeg\r\n\r\n' + b'\x00' * CHUNK + b'\r\n')
        else:
            yield (b'--frame\r\n'
                   b'Content-Type: audio/mpeg\r\n\r\n' + b'\x00' * CHUNK + b'\r\n')

@app.route('/audio_feed')
def audio_feed():
    return Response(audio_stream(),
                    mimetype='audio/mpeg')

@app.route('/toggle_mute', methods=['POST'])
def toggle_mute():
    global is_muted
    is_muted = not is_muted
    return jsonify({"status": "Muted" if is_muted else "Unmuted"})

if __name__ == '__main__':
    setup_ap()
    initialize_network()
    network_thread = threading.Thread(target=check_and_switch_network)
    network_thread.daemon = True
    network_thread.start()
    app.run(host='0.0.0.0', port=8080, threaded=True)