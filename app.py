import asyncio
import json
import os
import threading
import queue

from flask import Flask, render_template, request, Response, jsonify

from index import run

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/stream', methods=['POST'])
def stream_api():
    data = request.get_json()
    prompt = data.get('prompt')
    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400

    def generate():
        q = queue.Queue()

        async def emit(msg):
            q.put(msg)
            # Yield control slightly just to be safe
            await asyncio.sleep(0.01)

        def runner():
            try:
                asyncio.run(run(prompt, emit=emit))
            except Exception as e:
                q.put(f"ERROR: An internal error occurred: {e}")
            finally:
                q.put(None) # Signal completion

        thread = threading.Thread(target=runner)
        thread.start()

        while True:
            msg = q.get()
            if msg is None:
                break
            # SSE format
            yield f"data: {json.dumps({'message': msg})}\n\n"

        yield "data: {\"done\": true}\n\n"

    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
