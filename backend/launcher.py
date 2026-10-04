import threading, time, webbrowser
import uvicorn
from app.main import app  # direct import: PyInstaller sees the whole app and a startup error is shown instead of 'could not import app.main'

def open_ui():
    time.sleep(1.4)
    webbrowser.open('http://127.0.0.1:8000/desktop')

if __name__ == '__main__':
    threading.Thread(target=open_ui, daemon=True).start()
    uvicorn.run(app, host='127.0.0.1', port=8000, log_level='warning')
