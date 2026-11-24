"""Offline deployment configuration checks for the existing travel runner."""
from pathlib import Path
from urllib.parse import urlsplit


def travel_preflight(env, state_path, *, scheduled=False, inbox=False):
    """Return capability names only. Never open state or contact providers."""
    def value(name):
        return env.get(name, "").strip()

    def https(name, *, origin=False):
        try:
            raw = value(name)
            u = urlsplit(raw)
            u.port  # Validate port even though this code does not connect.
            return (u.scheme == "https" and bool(u.hostname)
                    and not (u.username is not None or u.password is not None or u.fragment)
                    and not any(c.isspace() or c == chr(92) for c in raw)
                    and (not origin or (u.path in ("", "/") and not u.query)))
        except ValueError:
            return False

    def oauth(prefix):
        direct = bool(value(prefix + "ACCESS_TOKEN"))
        refresh = all(value(prefix + n) for n in ("CLIENT_ID", "CLIENT_SECRET", "REFRESH_TOKEN"))
        # Existing provider chooses direct access token before refresh configuration.
        return (refresh and not direct) if scheduled else (direct or refresh)

    state = Path(state_path)
    state_ok = state.is_absolute() and state.parent.is_dir() and not state.is_symlink()
    if state_ok and state.exists():
        state_ok = state.is_file()
    recipients = [s.strip() for s in value("HOUSE_TRAVEL_RECIPIENTS").split(",") if s.strip()]
    capabilities = {
        "state_path": state_ok,
        "canonical_house": bool(https("HOUSE_SUPABASE_URL", origin=True)
            and all(value(n) for n in ("HOUSE_SUPABASE_SERVICE_ROLE_KEY", "HOUSE_TRAVEL_OWNER",
                "HOUSE_TRAVEL_CATEGORY", "HOUSE_TRAVEL_SOURCE_AGENT"))
            and value("HOUSE_TRAVEL_VISIBILITY") in ("private", "shared")),
        "calendar": bool(value("HOUSE_TRAVEL_TARGET") and value("HOUSE_TRAVEL_CALENDAR_REF")
            and oauth("HOUSE_GOOGLE_")),
        "traffic": bool(value("HOUSE_ROUTES_API_KEY")),
        "notifications": bool(https("HOUSE_TRAVEL_NOTIFY_URL") and value("HOUSE_TRAVEL_NOTIFY_TOKEN")
            and recipients and len(recipients) == len(set(recipients))),
    }
    if inbox:
        capabilities["mailbox"] = bool(value("HOUSE_TRAVEL_GMAIL_QUERY")
            and oauth("HOUSE_TRAVEL_GMAIL_"))
    # Offline checks cannot establish grants, state privacy, writer isolation or delivery.
    return {"configuration_ready": all(capabilities.values()), "configuration_only": True,
            "capabilities": capabilities, "live_verified": False}
