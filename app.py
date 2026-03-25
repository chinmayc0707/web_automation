from flask import Flask, render_template, request, Response, jsonify
import requests
import json

app = Flask(__name__)


import urllib.parse
import re

def is_safe_host(url):
    try:
        # If no scheme is provided, prepend http:// for parsing
        if not url.startswith('http://') and not url.startswith('https://'):
            url = 'http://' + url

        parsed = urllib.parse.urlparse(url)
        if not parsed.hostname:
            return False

        # Allow localhost, 127.0.0.1, host.docker.internal, and .local domains
        if parsed.hostname in ['localhost', '127.0.0.1', 'host.docker.internal'] or parsed.hostname.endswith('.local'):
            return True

        # Allow ngrok tunnels for testing remote Ollama instances
        if parsed.hostname.endswith('.ngrok-free.app') or parsed.hostname.endswith('.ngrok.io') or parsed.hostname.endswith('.ngrok.app'):
            return True

        # Allow local network ranges
        if parsed.hostname.startswith('192.168.') or parsed.hostname.startswith('10.'):
            return True

        if re.match(r'^172\.(1[6-9]|2[0-9]|3[0-1])\.', parsed.hostname):
            return True

        return False
    except Exception:
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    if not data:
        return jsonify({"error": "No JSON payload provided"}), 400

    host = data.get('host', 'http://localhost:11434')
    if not host.startswith('http://') and not host.startswith('https://'):
        host = 'http://' + host

    if not is_safe_host(host):
        return jsonify({"error": "Invalid or unsafe host URL"}), 400

    model = data.get('model', 'llama3')
    messages = data.get('messages', [])

    ollama_url = f"{host.rstrip('/')}/api/chat"

    payload = {
        "model": model,
        "messages": messages,
        "stream": True
    }

    def generate():
        try:
            with requests.post(ollama_url, json=payload, stream=True) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if line:
                        yield line + b'\n'
        except Exception as e:
            yield json.dumps({"error": str(e)}).encode('utf-8') + b'\n'

    return Response(generate(), mimetype='application/x-ndjson')

@app.route('/api/tags', methods=['GET'])
def get_tags():
    host = request.args.get('host', 'http://localhost:11434')
    if not host.startswith('http://') and not host.startswith('https://'):
        host = 'http://' + host

    if not is_safe_host(host):
        return jsonify({"error": "Invalid or unsafe host URL"}), 400

    try:
        # Short timeout so it fails fast if not running
        response = requests.get(f"{host.rstrip('/')}/api/tags", timeout=3)
        response.raise_for_status()
        return jsonify(response.json())
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Connection refused. Is Ollama running?", "models": []}), 200
    except Exception as e:
        return jsonify({"error": str(e), "models": []}), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)
