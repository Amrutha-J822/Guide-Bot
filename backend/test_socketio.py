from flask import Flask
from flask_socketio import SocketIO

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

@app.route('/')
def index():
    return "Test server is running!"

if __name__ == '__main__':
    print("About to start minimal SocketIO server...")
    socketio.run(app, debug=False, host='0.0.0.0', port=5000) 