#!/usr/bin/env python3
"""
setup_keys.py — one-shot key bootstrap for doctask-tej-thakar
==============================================================
Run once from the project root:

    python setup_keys.py

What it does:
  1. Checks ~/.superdocs/agent_credentials.json for an existing SuperDocs account
     (so we never create duplicate accounts).
  2. If none exists, signs up via POST /v1/agents/signup — fully agentic, no browser needed.
  3. Saves the full signup response to ~/.superdocs/agent_credentials.json.
  4. Writes (or updates) .env with SUPERDOCS_API_KEY and GROQ_API_KEY.

After this script runs, do `docker-compose up --build` and you're live.

Groq key (free):
  Get one at https://console.groq.com → API Keys → Create new key
  Model used: llama-3.3-70b-versatile (free, 280 tok/s)

SuperDocs promo:
  If you want 10,000 extra ops, redeem code BUILDER26 at
  use.superdocs.app → Settings → Billing after the account is created.
"""

import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' not installed. Run:  pip install requests")
    sys.exit(1)

SUPERDOCS_SIGNUP_URL = "https://api.superdocs.app/v1/agents/signup"
SUPERDOCS_WHOAMI_URL = "https://api.superdocs.app/v1/agents/whoami"
CREDENTIALS_PATH     = Path.home() / ".superdocs" / "agent_credentials.json"
PROJECT_ROOT         = Path(__file__).parent
ENV_PATH             = PROJECT_ROOT / ".env"
ENV_EXAMPLE_PATH     = PROJECT_ROOT / ".env.example"


def load_existing_credentials() -> dict | None:
    """Return saved credentials if they exist and the key still works."""
    if not CREDENTIALS_PATH.exists():
        return None
    try:
        creds = json.loads(CREDENTIALS_PATH.read_text())
        api_key = creds.get("api_key", "")
        if not api_key:
            return None
        resp = requests.get(
            SUPERDOCS_WHOAMI_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        if resp.status_code == 200:
            print(f"✓ Reusing existing SuperDocs account: {creds.get('slug', '?')}")
            print(f"  Remaining quota: {resp.json().get('quota', {}).get('remaining', '?')} ops")
            return creds
        print(f"⚠ Saved key returned {resp.status_code} — will sign up fresh.")
        return None
    except Exception as e:
        print(f"⚠ Could not verify saved credentials ({e}) — will sign up fresh.")
        return None


def signup() -> dict:
    """Create a new SuperDocs agent account."""
    print("→ Signing up for SuperDocs agent account…")
    resp = requests.post(
        SUPERDOCS_SIGNUP_URL,
        json={
            "terms_accepted": True,
            "agent_name": "doctask-tej-thakar",
            "operated_by_email": "thakartej12@gmail.com",
            "model_metadata": {
                "model":   "llama-3.3-70b-versatile (Groq)",
                "project": "doctask-tej-thakar",
                "purpose": "Agentic Indian insurance claims document analysis",
            },
        },
        timeout=20,
    )
    if resp.status_code not in (200, 201):
        print(f"ERROR: Signup failed ({resp.status_code}): {resp.text[:300]}")
        sys.exit(1)

    data = resp.json()
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(data, indent=2))
    os.chmod(CREDENTIALS_PATH, 0o600)

    print(f"✓ Account created: {data['slug']}")
    print(f"  Email:  {data['email']}")
    print(f"  Quota:  {data['quota']['remaining']} ops remaining (free tier: {data['quota']['monthly_limit']}/month)")
    print(f"  Saved to: {CREDENTIALS_PATH}")
    return data


def read_env() -> dict:
    """Parse an existing .env file into a dict."""
    env = {}
    src = ENV_PATH if ENV_PATH.exists() else ENV_EXAMPLE_PATH
    for line in src.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    return env


def write_env(env: dict) -> None:
    """Write the .env file, preserving comments from .env.example."""
    if not ENV_EXAMPLE_PATH.exists():
        # Fallback: write bare key=value pairs
        lines = [f"{k}={v}" for k, v in env.items()]
        ENV_PATH.write_text("\n".join(lines) + "\n")
        return

    output_lines = []
    written_keys = set()

    for line in ENV_EXAMPLE_PATH.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            output_lines.append(line)
            continue
        if "=" in stripped:
            k, _, _ = stripped.partition("=")
            k = k.strip()
            if k in env:
                output_lines.append(f"{k}={env[k]}")
                written_keys.add(k)
            else:
                output_lines.append(line)  # preserve original if we have no override
        else:
            output_lines.append(line)

    # Append any keys not in the example template
    for k, v in env.items():
        if k not in written_keys:
            output_lines.append(f"{k}={v}")

    ENV_PATH.write_text("\n".join(output_lines) + "\n")


def main():
    print("=" * 56)
    print("  doctask-tej-thakar  —  API key bootstrap")
    print("=" * 56)
    print()

    # ── SuperDocs ──────────────────────────────────────────
    creds = load_existing_credentials()
    if not creds:
        creds = signup()

    superdocs_key = creds["api_key"]

    # ── Groq ───────────────────────────────────────────────
    existing_env = read_env()
    groq_key = existing_env.get("GROQ_API_KEY", "")

    if not groq_key:
        print()
        print("─" * 56)
        print("Groq API key needed (free at console.groq.com):")
        print("  1. Go to  https://console.groq.com/keys")
        print("  2. Click 'Create API Key'")
        print("  3. Paste it below (or press Enter to skip for now)")
        print("─" * 56)
        groq_key = input("GROQ_API_KEY: ").strip()
    else:
        print(f"✓ GROQ_API_KEY already set in env.")

    # ── Write .env ─────────────────────────────────────────
    new_env = dict(existing_env)
    new_env["SUPERDOCS_API_KEY"] = superdocs_key
    if groq_key:
        new_env["GROQ_API_KEY"] = groq_key

    write_env(new_env)
    print()
    print(f"✓ .env written to {ENV_PATH}")

    # ── Summary ────────────────────────────────────────────
    print()
    print("=" * 56)
    print("  All done! Next steps:")
    print()
    print("  1. (optional) Redeem promo BUILDER26 at")
    print("     use.superdocs.app → Settings → Billing")
    print("     for 10,000 extra operations.")
    print()
    print("  2. Start the stack:")
    print("       docker-compose up --build")
    print()
    print("  3. Open http://localhost:3000")
    print("=" * 56)


if __name__ == "__main__":
    main()
