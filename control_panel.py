import os

from flask import Flask, jsonify, render_template, request

from bot_controller import BotController


app = Flask(__name__, template_folder="templates", static_folder="static")
controller = BotController(bot_script="main.py")


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/status")
def status():
    return jsonify(controller.status())


@app.get("/api/logs")
def logs():
    lines = request.args.get("lines", default=200, type=int)
    return jsonify({"logs": controller.get_logs(limit=lines)})


@app.post("/api/clear-logs")
def clear_logs():
    controller.clear_logs()
    return jsonify({"ok": True, "message": "Logs cleared."})


@app.post("/api/start")
def start():
    result = controller.start()
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.post("/api/stop")
def stop():
    result = controller.stop()
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.post("/api/restart")
def restart():
    result = controller.restart()
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.get("/api/meta")
def meta():
    return jsonify(
        {
            "name": "Discord Bot Control Panel",
            "vercel_note": (
                "Vercel serverless functions are not persistent. "
                "Use a persistent host for true 24/7 bot runtime."
            ),
        }
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
