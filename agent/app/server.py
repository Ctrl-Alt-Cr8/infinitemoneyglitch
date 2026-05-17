import io
import json
import os
import sys
import threading
import logging

# When run as `python app/server.py`, Python adds agent/app/ to sys.path instead
# of agent/, so package imports like `from app.storage...` would fail. Fix it.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

import firebase_admin
from firebase_admin import auth, credentials
from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB upload limit

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _init_firebase():
    if firebase_admin._apps:
        return
    sa = os.environ.get("FIREBASE_SERVICE_ACCOUNT", "firebase-service-account.json")
    if os.path.isfile(sa):
        cred = credentials.Certificate(sa)
    else:
        cred = credentials.Certificate(json.loads(sa))
    firebase_admin.initialize_app(cred)


_init_firebase()

from app.storage.grant_store import init_db
init_db()


def _verify_token(req) -> tuple[str | None, str | None]:
    """Extract and verify Firebase ID token. Returns (user_id, error_message)."""
    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None, "Missing Authorization header"
    token = auth_header.split("Bearer ", 1)[1].strip()
    try:
        decoded = auth.verify_id_token(token)
        return decoded["uid"], None
    except auth.ExpiredIdTokenError:
        return None, "Token expired"
    except auth.InvalidIdTokenError:
        return None, "Invalid token"
    except Exception as e:
        return None, f"Auth error: {e}"


def _run_pipeline_background(user_id: str):
    try:
        logger.info(f"Background pipeline started for user {user_id}")
        from app.main import run_pipeline
        run_pipeline(user_id=user_id)
        logger.info(f"Background pipeline complete for user {user_id}")
    except Exception as e:
        logger.error(f"Background pipeline failed for user {user_id}: {e}")


@app.route("/")
def health():
    return {"status": "infinite-money-glitch agent running"}


@app.route("/run-agent", methods=["POST"])
def run_agent():
    user_id, error = _verify_token(request)
    if error:
        return jsonify({"error": error}), 401
    try:
        thread = threading.Thread(target=_run_pipeline_background, args=(user_id,), daemon=True)
        thread.start()
        logger.info(f"Pipeline triggered for user {user_id}")
        return jsonify({"status": "pipeline started", "message": "running in background"}), 202
    except Exception as e:
        logger.error(f"Failed to start pipeline thread: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/config", methods=["GET"])
def get_config():
    user_id, error = _verify_token(request)
    if error:
        return jsonify({"error": error}), 401
    try:
        from app.storage.grant_store import get_user_config
        cfg = get_user_config(user_id)
        return jsonify({
            "name": cfg.name,
            "disciplines": cfg.disciplines,
            "org_type": cfg.org_type,
            "location_pref": cfg.location_pref,
            "geographic_focus": cfg.geographic_focus,
            "keywords": cfg.keywords,
            "summary": cfg.summary,
            "constraints": cfg.constraints,
            "project_description": cfg.project_description,
            "past_grants": cfg.past_grants,
            "budget_min": cfg.budget_min,
            "deadline_window_days": cfg.deadline_window_days,
            "scoring_weights": cfg.scoring_weights,
            "recipient_email": cfg.recipient_email,
        })
    except ValueError:
        return jsonify({"error": "no config"}), 404
    except Exception as e:
        logger.error(f"/config error for {user_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/parse-resume", methods=["POST"])
def parse_resume():
    """Parse artist CV, artist statement, or past grant application."""
    user_id, error = _verify_token(request)
    if error:
        return jsonify({"error": error}), 401

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are accepted"}), 400

    try:
        import pypdf
        pdf_bytes = file.read()
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()

        if len(text) < 100:
            return jsonify({"error": "Could not extract enough text from PDF — try a text-based PDF"}), 422

        interview_answers = request.form.get("interview_answers", "")
        from app.utils.claude_client import parse_resume_with_claude
        parsed = parse_resume_with_claude(text, interview_answers=interview_answers)
        logger.info(f"Document parsed for user {user_id}")
        return jsonify(parsed)
    except Exception as e:
        logger.error(f"/parse-resume error for {user_id}: {e}")
        return jsonify({"error": f"Document parsing failed: {e}"}), 500


@app.route("/runs", methods=["GET"])
def get_runs():
    user_id, error = _verify_token(request)
    if error:
        return jsonify({"error": error}), 401
    try:
        from app.storage.grant_store import get_runs_with_grants
        runs = get_runs_with_grants(user_id)
        return jsonify(runs)
    except Exception as e:
        logger.error(f"/runs error for {user_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/onboard", methods=["POST"])
def onboard():
    user_id, error = _verify_token(request)
    if error:
        return jsonify({"error": error}), 401

    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    recipient_email = (data.get("recipient_email") or "").strip()
    if not recipient_email:
        return jsonify({"error": "recipient_email is required"}), 400

    disciplines = [d.strip() for d in (data.get("disciplines") or []) if d.strip()]
    org_type = (data.get("org_type") or "individual").strip()
    location_pref = (data.get("location_pref") or "").strip()
    geographic_focus = [g.strip() for g in (data.get("geographic_focus") or []) if g.strip()]
    keywords = [k.strip() for k in (data.get("keywords") or []) if k.strip()]
    summary = (data.get("summary") or "").strip()
    constraints = (data.get("constraints") or "").strip()
    project_description = (data.get("project_description") or "").strip()
    past_grants = (data.get("past_grants") or "").strip()
    budget_min = int(data.get("budget_min") or 0)
    deadline_window_days = int(data.get("deadline_window_days") or 90)
    scoring_weights = data.get("scoring_weights") or {"mission": "high", "award": "medium", "deadline": "medium"}
    interview_answers = (data.get("interview_answers") or "").strip()

    try:
        firebase_user = auth.get_user(user_id)
        email = firebase_user.email or recipient_email

        from app.storage.grant_store import save_user, save_user_config
        save_user(user_id, email)
        save_user_config(
            user_id=user_id,
            name=name,
            disciplines=disciplines,
            org_type=org_type,
            location_pref=location_pref,
            geographic_focus=geographic_focus,
            keywords=keywords,
            summary=summary,
            constraints=constraints,
            recipient_email=recipient_email,
            project_description=project_description,
            past_grants=past_grants,
            budget_min=budget_min,
            deadline_window_days=deadline_window_days,
            scoring_weights=scoring_weights,
            interview_answers=interview_answers,
        )
        logger.info(f"Onboarding complete for user {user_id}")
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"/onboard error for {user_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/draft-document", methods=["POST"])
def draft_document():
    """On-demand LOI or artist statement generation for a specific grant."""
    user_id, error = _verify_token(request)
    if error:
        return jsonify({"error": error}), 401

    data = request.get_json(silent=True) or {}
    grant_id = data.get("grant_id")
    doc_type = (data.get("doc_type") or "").strip().lower()

    if doc_type not in ("loi", "artist_statement"):
        return jsonify({"error": "doc_type must be 'loi' or 'artist_statement'"}), 400

    try:
        from app.storage.grant_store import get_grant, get_user_config, save_draft
        from app.composer.loi_generator import generate_loi, generate_artist_statement

        cfg = get_user_config(user_id)
        profile = cfg.as_profile()

        grant = get_grant(grant_id) if grant_id else None

        if doc_type == "loi":
            if not grant:
                return jsonify({"error": "grant_id required for LOI"}), 400
            result = generate_loi(grant, profile)
        else:
            result = generate_artist_statement(profile, grant=grant)

        content = result.get("text", "")
        if not content:
            return jsonify({"error": "Document generation failed", "issues": result.get("issues", [])}), 500

        draft_id = save_draft(user_id, grant_id, doc_type, content)

        return jsonify({
            "id": draft_id,
            "doc_type": doc_type,
            "content": content,
            "valid": result.get("valid", True),
            "issues": result.get("issues", []),
            "grant_title": grant.get("title") if grant else None,
            "funder": grant.get("funder") if grant else None,
        })
    except ValueError:
        return jsonify({"error": "no config — complete onboarding first"}), 404
    except Exception as e:
        logger.error(f"/draft-document error for {user_id}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/drafts", methods=["GET"])
def get_drafts():
    """List all saved drafts for the authenticated user."""
    user_id, error = _verify_token(request)
    if error:
        return jsonify({"error": error}), 401
    try:
        from app.storage.grant_store import get_drafts
        drafts = get_drafts(user_id)
        return jsonify(drafts)
    except Exception as e:
        logger.error(f"/drafts error for {user_id}: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
