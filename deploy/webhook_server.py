import hashlib
import hmac
import os
import subprocess

from flask import Flask, abort, jsonify, request


app = Flask(__name__)

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
TARGET_BRANCH = os.getenv("TARGET_BRANCH", "main")
DEPLOY_SCRIPT = os.getenv("DEPLOY_SCRIPT", "/repo/deploy/deploy.sh")


def verify_signature(raw_body, signature_header):
    if not WEBHOOK_SECRET:
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    sent = signature_header.split("=", 1)[1]
    digest = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sent, digest)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/github-webhook")
def github_webhook():
    signature = request.headers.get("X-Hub-Signature-256", "")
    event = request.headers.get("X-GitHub-Event", "")
    body = request.get_data()

    if not verify_signature(body, signature):
        abort(401, "Invalid webhook signature")

    if event != "push":
        return jsonify({"ignored": True, "reason": "not push event"}), 200

    payload = request.get_json(silent=True) or {}
    pushed_ref = payload.get("ref", "")
    expected_ref = f"refs/heads/{TARGET_BRANCH}"
    if pushed_ref != expected_ref:
        return jsonify({"ignored": True, "reason": f"ref {pushed_ref} != {expected_ref}"}), 200

    proc = subprocess.run(["/bin/sh", DEPLOY_SCRIPT], capture_output=True, text=True)
    if proc.returncode != 0:
        return (
            jsonify(
                {
                    "deployed": False,
                    "code": proc.returncode,
                    "stdout": proc.stdout,
                    "stderr": proc.stderr,
                }
            ),
            500,
        )

    return jsonify({"deployed": True, "stdout": proc.stdout, "stderr": proc.stderr}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000)
