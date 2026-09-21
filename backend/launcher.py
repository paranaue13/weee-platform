import threading, time, webbrowser
import uvicorn

def open_ui():
    time.sleep(1.4)
    webbrowser.open('http://127.0.0.1:8000/desktop')

if __name__ == '__main__':
    threading.Thread(target=open_ui, daemon=True).start()
    uvicorn.run('app.main:app', host='127.0.0.1', port=8000, log_level='warning')
