import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path


class ReviewerAuthError(PermissionError):
    pass


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ReviewerRegistry:
    def __init__(self, path):
        if not path:
            raise ValueError("Reviewer registry is not configured")
        self.path = Path(path)
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("schema_version") != 1 or not value.get("reviewers"):
            raise ValueError("Reviewer registry is invalid")
        self.reviewers = value["reviewers"]

    def authenticate(self, authorization):
        if not authorization or not authorization.startswith("Bearer "):
            raise ReviewerAuthError("Reviewer bearer token is required")
        supplied = token_hash(authorization[7:].strip())
        for item in self.reviewers:
            if item.get("active", True) and hmac.compare_digest(
                    supplied, item.get("token_sha256", "")):
                if item.get("role") != "reviewer":
                    raise ReviewerAuthError("Reviewer role is required")
                return {"reviewer_id": item["reviewer_id"], "role": item["role"]}
        raise ReviewerAuthError("Reviewer bearer token is invalid")


def initialize_reviewer(registry_path, token_path, reviewer_id):
    if not reviewer_id or len(reviewer_id) > 64:
        raise ValueError("reviewer_id must contain 1-64 characters")
    registry_path, token_path = Path(registry_path), Path(token_path)
    if registry_path.exists() or token_path.exists():
        raise FileExistsError("Reviewer secret files already exist")
    token = secrets.token_urlsafe(32)
    registry = {"schema_version": 1, "reviewers": [{
        "reviewer_id": reviewer_id, "role": "reviewer",
        "token_sha256": token_hash(token), "active": True,
    }]}
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    token_path.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(registry_path, 0o600)
        os.chmod(token_path, 0o600)
    except OSError:
        pass
    return {"reviewer_id": reviewer_id, "registry": str(registry_path),
            "token_file": str(token_path), "token_sha256": token_hash(token)}
