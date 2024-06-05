from flask import Flask, jsonify, render_template, request, send_file
from flask_mysqldb import MySQL
from flask_socketio import SocketIO, emit
import serial
import time
import json
from threading import Thread, Lock

app = Flask(__name__)
socketio = SocketIO(app)

# Configuration for MySQL
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'slovakia'
app.config['MYSQL_DB'] = 'sensor_data'
mysql = MySQL(app)

ser = None
monitoring_thread = None
monitoring_active = False
lock = Lock()

# File path for JSON data
data_file = 'sensor_data.json'
last_save_time = 0

def initialize_system():
    global ser
    try:
        ser = serial.Serial('/dev/tty.usbmodem1412201', 9600, timeout=1)
        return True, "Serial connection established with Arduino."
    except Exception as e:
        return False, f"Error initializing system: {e}"

def read_from_arduino():
    global monitoring_active, last_save_time
    while monitoring_active:
        if ser:
            data = ser.readline().decode().strip()
            if data:
                try:
                    if "Distance:" in data and "Position:" in data:
                        distance_data = data.split(",")[0].split(":")[1].strip()
                        position_data = data.split(",")[1].split(":")[1].strip()
                        distance = ''.join(filter(str.isdigit, distance_data))
                        position = ''.join(filter(str.isdigit, position_data))
                        if distance and position:
                            store_data(distance, position)
                            current_time = time.time()
                            if current_time - last_save_time >= 10:
                                save_to_json(distance, position)
                                last_save_time = current_time
                            socketio.emit('sensor_update', {'distance': distance, 'position': position})
                    elif "New threshold:" in data:
                        print(data)
                    else:
                        print("Data format error:", data)
                except ValueError as e:
                    print("Error processing incoming data:", e)
                except Exception as e:
                    print("Unexpected error:", e)
            socketio.sleep(0.5)

def store_data(distance, position):
    with app.app_context():
        cur = mysql.connection.cursor()
        try:
            cur.execute("INSERT INTO measurements (distance, position) VALUES (%s, %s)", (distance, position))
            mysql.connection.commit()
        except Exception as e:
            print("Failed to insert data:", e)
        finally:
            cur.close()

def save_to_json(distance, position):
    with lock:
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        entry = {"timestamp": timestamp, "distance": distance, "position": position}

        try:
            with open(data_file, 'r') as f:
                data = json.load(f)
        except FileNotFoundError:
            data = []

        data.append(entry)

        with open(data_file, 'w') as f:
            json.dump(data, f, indent=4)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/open', methods=['POST'])
def open_system():
    success, message = initialize_system()
    if success:
        return jsonify({'status': 'System initialized and sensors activated', 'message': message})
    else:
        return jsonify({'status': 'Initialization failed', 'message': message})

@app.route('/settings', methods=['POST'])
def update_settings():
    data = request.json
    threshold = data.get('threshold')
    if ser:
        ser.write(f'{threshold}\n'.encode())
        return jsonify({'status': 'Settings updated', 'threshold': threshold})
    else:
        return jsonify({'status': 'Error: Serial connection not established'})

@app.route('/start', methods=['POST'])
def start():
    global monitoring_thread, monitoring_active
    if not monitoring_active:
        monitoring_active = True
        monitoring_thread = Thread(target=read_from_arduino)
        monitoring_thread.start()
    return jsonify({'status': 'Monitoring started'})

@app.route('/stop', methods=['POST'])
def stop():
    global monitoring_active
    monitoring_active = False
    return jsonify({'status': 'Monitoring stopped'})

@app.route('/close', methods=['POST'])
def close_system():
    global ser, monitoring_thread, monitoring_active
    if ser:
        ser.write(b'stop')
        ser.close()
        ser = None
    if monitoring_thread:
        monitoring_active = False
        monitoring_thread = None
    return jsonify({'status': 'System deactivated and connection closed'})

@app.route('/data')
def data():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM measurements ORDER BY timestamp DESC LIMIT 1")
    record = cursor.fetchone()
    if record:
        return jsonify({'distance': record[2], 'position': record[3]})
    else:
        return jsonify({'error': 'No data found'})

@app.route('/json_data', methods=['GET'])
def json_data():
    return send_file(data_file)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
