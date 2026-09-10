from flask import Flask, jsonify

app = Flask(__name__)


@app.get("/")
def home():
    return jsonify(message="Hello from CI/CD!")


@app.get("/health")
def health():
    return jsonify(status="ok"), 503


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
