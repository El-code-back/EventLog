from __future__ import annotations

import json
import secrets
import sqlite3
import string
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).parent
STATIC_DIR = ROOT / "static"
DB_PATH = ROOT / "eventlog.sqlite3"

EVENT_TYPES = ("hackathon", "webinar", "conference", "workshop", "challenge", "meeting")
LEVELS = ("local", "interuniversity", "international", "online")
PARTICIPATION_STATUSES = ("planned", "attended", "cancelled", "interested")
VISIBILITY_SCOPES = ("all", "friends", "team", "private")
TEAM_VISIBILITY = ("team_only", "public_anonymous", "hidden")
INVITE_STATUSES = ("pending", "accepted", "declined")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def short_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def token() -> str:
    return secrets.token_urlsafe(12)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def dumps(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    data = dict(row)
    if "preferences" in data and isinstance(data["preferences"], str):
        data["preferences"] = json.loads(data["preferences"] or "{}")
    if "tags" in data and isinstance(data["tags"], str):
        data["tags"] = [tag for tag in data["tags"].split(",") if tag]
    return data


def add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})")]
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                pin TEXT,
                invite_code TEXT NOT NULL UNIQUE,
                invite_token TEXT NOT NULL UNIQUE,
                joined_at TEXT NOT NULL,
                preferences TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS friendships (
                requester_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                addressee_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                responded_at TEXT,
                PRIMARY KEY (requester_id, addressee_id)
            );

            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                invite_token TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS team_members (
                team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL DEFAULT 'member',
                joined_at TEXT NOT NULL,
                PRIMARY KEY (team_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS team_invitations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                invited_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                invited_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                responded_at TEXT
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                type TEXT NOT NULL,
                level TEXT NOT NULL,
                link TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                is_private INTEGER NOT NULL DEFAULT 0,
                visibility_scope TEXT NOT NULL DEFAULT 'all',
                created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_events (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'planned',
                notes TEXT NOT NULL DEFAULT '',
                participation_marked_at TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'self',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, event_id)
            );

            CREATE TABLE IF NOT EXISTS team_events (
                team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                visibility TEXT NOT NULL DEFAULT 'team_only',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (team_id, event_id)
            );

            CREATE TABLE IF NOT EXISTS comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        add_column(conn, "users", "pin", "TEXT")
        add_column(conn, "users", "invite_code", "TEXT")
        add_column(conn, "users", "invite_token", "TEXT")
        add_column(conn, "teams", "invite_token", "TEXT")
        add_column(conn, "team_members", "role", "TEXT NOT NULL DEFAULT 'member'")
        add_column(conn, "user_events", "participation_marked_at", "TEXT")
        add_column(conn, "user_events", "source", "TEXT NOT NULL DEFAULT 'self'")
        for row in conn.execute("SELECT id FROM users WHERE invite_code IS NULL OR invite_token IS NULL").fetchall():
            conn.execute(
                "UPDATE users SET invite_code = COALESCE(invite_code, ?), invite_token = COALESCE(invite_token, ?) WHERE id = ?",
                (short_code(), token(), row["id"]),
            )
        for row in conn.execute("SELECT id FROM teams WHERE invite_token IS NULL").fetchall():
            conn.execute("UPDATE teams SET invite_token = ? WHERE id = ?", (token(), row["id"]))
        conn.execute(
            "UPDATE user_events SET participation_marked_at = COALESCE(participation_marked_at, updated_at, ?) WHERE participation_marked_at IS NULL",
            (now_iso(),),
        )


def visible_events_sql(view: str) -> str:
    if view == "mine":
        return "ue.user_id = :user_id"
    if view == "team":
        return "te.team_id IS NOT NULL"
    return ""


def get_events(conn: sqlite3.Connection, params: dict[str, list[str]]) -> list[dict]:
    user_id = int(params.get("user_id", ["0"])[0] or 0)
    view = params.get("view", ["all"])[0]
    search = params.get("search", [""])[0].strip().lower()
    event_type = params.get("type", [""])[0]
    level = params.get("level", [""])[0]
    tag = params.get("tag", [""])[0].strip().lower()
    where = [visible_events_sql(view)] if visible_events_sql(view) else []
    values: dict[str, object] = {"user_id": user_id}
    if search:
        where.append("(LOWER(e.title) LIKE :search OR LOWER(e.description) LIKE :search)")
        values["search"] = f"%{search}%"
    if event_type:
        where.append("e.type = :type")
        values["type"] = event_type
    if level:
        where.append("e.level = :level")
        values["level"] = level
    if tag:
        where.append("LOWER(e.tags) LIKE :tag")
        values["tag"] = f"%{tag}%"
    clause = "WHERE " + " AND ".join(where) if where else ""
    rows = conn.execute(
        f"""
        SELECT e.*, u.name AS creator_name, ue.status, ue.notes, ue.source,
               ue.participation_marked_at, t.id AS team_id, t.name AS team_name,
               te.visibility AS team_visibility
        FROM events e
        LEFT JOIN users u ON u.id = e.created_by
        LEFT JOIN user_events ue ON ue.event_id = e.id AND ue.user_id = :user_id
        LEFT JOIN team_events te ON te.event_id = e.id
        LEFT JOIN teams t ON t.id = te.team_id
        {clause}
        ORDER BY e.start_date ASC
        """,
        values,
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def get_event(conn: sqlite3.Connection, event_id: int, user_id: int) -> dict | None:
    event = row_to_dict(
        conn.execute(
            """
            SELECT e.*, u.name AS creator_name, ue.status, ue.notes, ue.source,
                   ue.participation_marked_at, t.id AS team_id, t.name AS team_name,
                   te.visibility AS team_visibility
            FROM events e
            LEFT JOIN users u ON u.id = e.created_by
            LEFT JOIN user_events ue ON ue.event_id = e.id AND ue.user_id = ?
            LEFT JOIN team_events te ON te.event_id = e.id
            LEFT JOIN teams t ON t.id = te.team_id
            WHERE e.id = ?
            """,
            (user_id, event_id),
        ).fetchone()
    )
    if not event:
        return None
    event["participants"] = [
        row_to_dict(row)
        for row in conn.execute(
            """
            SELECT u.id, u.name, u.invite_code, ue.status, ue.source
            FROM user_events ue
            JOIN users u ON u.id = ue.user_id
            WHERE ue.event_id = ?
            ORDER BY u.name
            """,
            (event_id,),
        ).fetchall()
    ]
    event["teams"] = [
        row_to_dict(row)
        for row in conn.execute(
            """
            SELECT t.id, t.name, te.visibility
            FROM team_events te
            JOIN teams t ON t.id = te.team_id
            WHERE te.event_id = ?
            ORDER BY t.name
            """,
            (event_id,),
        ).fetchall()
    ]
    event["comments"] = [
        row_to_dict(row)
        for row in conn.execute(
            """
            SELECT c.id, c.body, c.created_at, u.name AS author
            FROM comments c
            JOIN users u ON u.id = c.user_id
            WHERE c.event_id = ?
            ORDER BY c.created_at DESC
            """,
            (event_id,),
        ).fetchall()
    ]
    return event


def empty_charts() -> dict:
    return {"periods": [], "types": [], "collaborators": [], "timeline": [], "summary": {}}


def get_dashboard(conn: sqlite3.Connection, user_id: int) -> dict:
    events = get_events(conn, {"user_id": [str(user_id)], "view": ["mine"]}) if user_id else []
    upcoming = [event for event in events if event["start_date"] >= datetime.now().isoformat(timespec="minutes")][:6]
    recent = sorted(events, key=lambda item: item.get("participation_marked_at") or item["created_at"], reverse=True)[:6]
    return {"upcoming": upcoming, "recent": recent}


def period_start(period: str) -> datetime:
    now = datetime.now(timezone.utc)
    if period == "week":
        return now - timedelta(days=7)
    if period == "year":
        return now - timedelta(days=365)
    return now - timedelta(days=31)


def get_user_analytics(conn: sqlite3.Connection, user_id: int, period: str = "month") -> dict:
    since = period_start(period).isoformat(timespec="seconds")
    rows = conn.execute(
        """
        SELECT e.*, ue.status, ue.participation_marked_at, ue.source
        FROM user_events ue
        JOIN events e ON e.id = ue.event_id
        WHERE ue.user_id = ? AND ue.participation_marked_at >= ?
        """,
        (user_id, since),
    ).fetchall()
    events = [row_to_dict(row) for row in rows]
    status_counts = {status: 0 for status in PARTICIPATION_STATUSES}
    type_counts: dict[str, int] = {}
    timeline: dict[str, int] = {}
    for event in events:
        status_counts[event["status"]] = status_counts.get(event["status"], 0) + 1
        if event["status"] == "attended":
            type_counts[event["type"]] = type_counts.get(event["type"], 0) + 1
        bucket = (event.get("participation_marked_at") or event["start_date"])[:10]
        timeline[bucket] = timeline.get(bucket, 0) + 1
    planned_like = status_counts.get("planned", 0) + status_counts.get("interested", 0) + status_counts.get("attended", 0)
    conversion = round((status_counts.get("attended", 0) / planned_like) * 100, 1) if planned_like else 0
    collaborators = [
        row_to_dict(row)
        for row in conn.execute(
            """
            SELECT u.id, u.name, u.invite_code, COUNT(*) AS shared_count
            FROM user_events mine
            JOIN user_events other ON other.event_id = mine.event_id AND other.user_id != mine.user_id
            JOIN users u ON u.id = other.user_id
            WHERE mine.user_id = ?
            GROUP BY u.id, u.name, u.invite_code
            ORDER BY shared_count DESC, u.name
            LIMIT 8
            """,
            (user_id,),
        ).fetchall()
    ]
    return {
        "summary": {
            "period": period,
            "planned": status_counts.get("planned", 0),
            "attended": status_counts.get("attended", 0),
            "interested": status_counts.get("interested", 0),
            "cancelled": status_counts.get("cancelled", 0),
            "conversion": conversion,
        },
        "periods": [
            {"label": "planned", "count": status_counts.get("planned", 0)},
            {"label": "attended", "count": status_counts.get("attended", 0)},
            {"label": "interested", "count": status_counts.get("interested", 0)},
            {"label": "cancelled", "count": status_counts.get("cancelled", 0)},
        ],
        "types": [{"label": key, "count": value} for key, value in sorted(type_counts.items())],
        "collaborators": collaborators,
        "timeline": [{"label": key, "count": timeline[key]} for key in sorted(timeline)],
    }


def get_team_analytics(conn: sqlite3.Connection, team_id: int) -> dict:
    rows = conn.execute(
        """
        SELECT ue.status, e.type, ue.participation_marked_at
        FROM team_events te
        JOIN user_events ue ON ue.event_id = te.event_id
        JOIN events e ON e.id = te.event_id
        WHERE te.team_id = ?
        """,
        (team_id,),
    ).fetchall()
    status_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    timeline: dict[str, int] = {}
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        if row["status"] == "attended":
            type_counts[row["type"]] = type_counts.get(row["type"], 0) + 1
        day = (row["participation_marked_at"] or now_iso())[:10]
        timeline[day] = timeline.get(day, 0) + 1
    planned_like = status_counts.get("planned", 0) + status_counts.get("interested", 0) + status_counts.get("attended", 0)
    conversion = round((status_counts.get("attended", 0) / planned_like) * 100, 1) if planned_like else 0
    return {
        "summary": {"attended": status_counts.get("attended", 0), "planned": status_counts.get("planned", 0), "conversion": conversion},
        "types": [{"label": key, "count": value} for key, value in sorted(type_counts.items())],
        "timeline": [{"label": key, "count": timeline[key]} for key in sorted(timeline)],
    }


def get_team(conn: sqlite3.Connection, team_id: int) -> dict | None:
    team = row_to_dict(
        conn.execute(
            """
            SELECT t.*, u.name AS creator_name
            FROM teams t
            JOIN users u ON u.id = t.created_by
            WHERE t.id = ?
            """,
            (team_id,),
        ).fetchone()
    )
    if not team:
        return None
    team["members"] = [
        row_to_dict(row)
        for row in conn.execute(
            """
            SELECT u.id, u.name, u.invite_code, tm.role, tm.joined_at
            FROM team_members tm
            JOIN users u ON u.id = tm.user_id
            WHERE tm.team_id = ?
            ORDER BY tm.role DESC, u.name
            """,
            (team_id,),
        ).fetchall()
    ]
    team["events"] = [
        row_to_dict(row)
        for row in conn.execute(
            """
            SELECT e.*, te.visibility AS team_visibility
            FROM team_events te
            JOIN events e ON e.id = te.event_id
            WHERE te.team_id = ?
            ORDER BY e.start_date ASC
            """,
            (team_id,),
        ).fetchall()
    ]
    team["analytics"] = get_team_analytics(conn, team_id)
    return team


def get_profile(conn: sqlite3.Connection, user_id: int) -> dict | None:
    user = row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
    if not user:
        return None
    user["friends"] = [
        row_to_dict(row)
        for row in conn.execute(
            """
            SELECT u.id, u.name, u.invite_code, COUNT(shared.event_id) AS shared_events
            FROM friendships f
            JOIN users u ON u.id = CASE WHEN f.requester_id = ? THEN f.addressee_id ELSE f.requester_id END
            LEFT JOIN user_events mine ON mine.user_id = ?
            LEFT JOIN user_events shared ON shared.user_id = u.id AND shared.event_id = mine.event_id
            WHERE (f.requester_id = ? OR f.addressee_id = ?) AND f.status = 'accepted'
            GROUP BY u.id, u.name, u.invite_code
            ORDER BY u.name
            """,
            (user_id, user_id, user_id, user_id),
        ).fetchall()
    ]
    user["teams"] = [
        row_to_dict(row)
        for row in conn.execute(
            """
            SELECT t.id, t.name, t.invite_token, tm.role
            FROM team_members tm
            JOIN teams t ON t.id = tm.team_id
            WHERE tm.user_id = ?
            ORDER BY t.name
            """,
            (user_id,),
        ).fetchall()
    ]
    user["friend_invites"] = [
        row_to_dict(row)
        for row in conn.execute(
            """
            SELECT f.requester_id, f.addressee_id, f.status, f.created_at, u.name AS from_name, u.invite_code AS from_code
            FROM friendships f
            JOIN users u ON u.id = f.requester_id
            WHERE f.addressee_id = ? AND f.status = 'pending'
            ORDER BY f.created_at DESC
            """,
            (user_id,),
        ).fetchall()
    ]
    user["team_invites"] = [
        row_to_dict(row)
        for row in conn.execute(
            """
            SELECT ti.id, ti.status, ti.created_at, t.name AS team_name, u.name AS from_name
            FROM team_invitations ti
            JOIN teams t ON t.id = ti.team_id
            JOIN users u ON u.id = ti.invited_by
            WHERE ti.invited_user_id = ? AND ti.status = 'pending'
            ORDER BY ti.created_at DESC
            """,
            (user_id,),
        ).fetchall()
    ]
    return user


def public_user(conn: sqlite3.Connection, user_id: int) -> dict | None:
    return row_to_dict(
        conn.execute(
            "SELECT id, name, invite_code, invite_token, joined_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    )


def public_user_by_invite(conn: sqlite3.Connection, invite_value: str) -> dict | None:
    value = invite_value.strip()
    if not value:
        return None
    return row_to_dict(
        conn.execute(
            """
            SELECT id, name, invite_code, invite_token, joined_at
            FROM users
            WHERE invite_token = ? OR invite_code = ?
            """,
            (value, value.upper()),
        ).fetchone()
    )


def create_user(conn: sqlite3.Connection, payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    pin = str(payload.get("pin", "")).strip() or None
    access_code = str(payload.get("access_code", "")).strip().upper()
    if len(name) < 2:
        raise ValueError("Имя должно содержать минимум 2 символа.")
    if access_code:
        existing = conn.execute(
            """
            SELECT * FROM users
            WHERE LOWER(name) = LOWER(?) AND (invite_code = ? OR COALESCE(pin, '') = ?)
            """,
            (name, access_code, access_code),
        ).fetchone()
        if existing:
            return row_to_dict(existing)
    existing = conn.execute(
        "SELECT * FROM users WHERE LOWER(name) = LOWER(?) AND COALESCE(pin, '') = COALESCE(?, '')",
        (name, pin),
    ).fetchone()
    if existing:
        return row_to_dict(existing)
    same_name = conn.execute("SELECT * FROM users WHERE LOWER(name) = LOWER(?) ORDER BY id", (name,)).fetchall()
    if len(same_name) == 1 and not pin and not access_code:
        return row_to_dict(same_name[0])
    if len(same_name) > 1 and not pin and not access_code:
        raise ValueError("Найдено несколько профилей с таким именем. Введите пин или invite-code.")
    conn.execute(
        "INSERT INTO users(name, pin, invite_code, invite_token, joined_at, preferences) VALUES (?, ?, ?, ?, ?, ?)",
        (name, pin, short_code(), token(), now_iso(), json.dumps({"defaultView": "mine", "interests": []}, ensure_ascii=False)),
    )
    return row_to_dict(conn.execute("SELECT * FROM users WHERE id = last_insert_rowid()").fetchone())


def create_event(conn: sqlite3.Connection, payload: dict) -> dict:
    required = ("title", "description", "start_date", "end_date", "type", "level")
    missing = [field for field in required if not str(payload.get(field, "")).strip()]
    if missing:
        raise ValueError(f"Заполните поля: {', '.join(missing)}")
    event_type = payload["type"]
    level = payload["level"]
    status = payload.get("status", "planned")
    if event_type not in EVENT_TYPES:
        raise ValueError("Неизвестный тип события.")
    if level not in LEVELS:
        raise ValueError("Неизвестный уровень события.")
    if status not in PARTICIPATION_STATUSES:
        raise ValueError("Неизвестный статус участия.")
    visibility_scope = payload.get("visibility_scope", "all")
    if visibility_scope not in VISIBILITY_SCOPES:
        raise ValueError("Неизвестная видимость события.")
    user_id = int(payload.get("created_by", 0))
    if not user_id:
        raise ValueError("Сначала создайте профиль.")
    tags = payload.get("tags", "")
    tags_value = ",".join(tag.strip() for tag in str(tags).split(",") if tag.strip())
    cur = conn.execute(
        """
        INSERT INTO events(
            title, description, start_date, end_date, type, level, link, tags,
            is_private, visibility_scope, created_by, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload["title"].strip(),
            payload["description"].strip(),
            payload["start_date"],
            payload["end_date"],
            event_type,
            level,
            payload.get("link", "").strip(),
            tags_value,
            1 if payload.get("is_private") else 0,
            visibility_scope,
            user_id,
            now_iso(),
        ),
    )
    event_id = cur.lastrowid
    stamp = now_iso()
    conn.execute(
        """
        INSERT INTO user_events(user_id, event_id, status, notes, participation_marked_at, source, updated_at)
        VALUES (?, ?, ?, ?, ?, 'self', ?)
        """,
        (user_id, event_id, status, payload.get("notes", ""), stamp, stamp),
    )
    team_id = payload.get("team_id")
    if team_id:
        visibility = payload.get("team_visibility", "team_only")
        if visibility not in TEAM_VISIBILITY:
            visibility = "team_only"
        conn.execute(
            "INSERT INTO team_events(team_id, event_id, visibility, updated_at) VALUES (?, ?, ?, ?)",
            (int(team_id), event_id, visibility, stamp),
        )
    return get_event(conn, event_id, user_id)


def search_users(conn: sqlite3.Connection, params: dict[str, list[str]]) -> list[dict]:
    name = params.get("name", [""])[0].strip().lower()
    code = params.get("code", [""])[0].strip().upper()
    invite_token = params.get("token", [""])[0].strip()
    if not name and not code and not invite_token:
        return []
    where = []
    values: dict[str, object] = {}
    if name:
        where.append("LOWER(name) LIKE :name")
        values["name"] = f"%{name}%"
    if code:
        where.append("invite_code = :code")
        values["code"] = code
    if invite_token:
        where.append("invite_token = :token")
        values["token"] = invite_token
    rows = conn.execute(
        f"SELECT id, name, invite_code, invite_token, joined_at FROM users WHERE {' AND '.join(where)} ORDER BY name LIMIT 20",
        values,
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def request_friend(conn: sqlite3.Connection, requester_id: int, target_id: int) -> dict:
    if requester_id == target_id:
        raise ValueError("Нельзя добавить себя в друзья.")
    low, high = sorted((requester_id, target_id))
    existing = conn.execute(
        """
        SELECT * FROM friendships
        WHERE (requester_id = ? AND addressee_id = ?) OR (requester_id = ? AND addressee_id = ?)
        """,
        (requester_id, target_id, target_id, requester_id),
    ).fetchone()
    if existing:
        if existing["status"] == "declined":
            conn.execute(
                "UPDATE friendships SET requester_id=?, addressee_id=?, status='pending', created_at=?, responded_at=NULL WHERE requester_id=? AND addressee_id=?",
                (requester_id, target_id, now_iso(), existing["requester_id"], existing["addressee_id"]),
            )
        return {"status": existing["status"]}
    conn.execute(
        "INSERT INTO friendships(requester_id, addressee_id, status, created_at) VALUES (?, ?, 'pending', ?)",
        (requester_id, target_id, now_iso()),
    )
    return {"status": "pending", "pair": [low, high]}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = dumps(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/invite/"):
            self.path = "/index.html"
            return super().do_GET()
        if not parsed.path.startswith("/api/"):
            if parsed.path in ("", "/"):
                self.path = "/index.html"
            return super().do_GET()
        params = parse_qs(parsed.query)
        try:
            with connect() as conn:
                if parsed.path == "/api/meta":
                    self.send_json(
                        {
                            "event_types": EVENT_TYPES,
                            "levels": LEVELS,
                            "statuses": PARTICIPATION_STATUSES,
                            "visibility_scopes": VISIBILITY_SCOPES,
                            "team_visibility": TEAM_VISIBILITY,
                        }
                    )
                elif parsed.path.startswith("/api/invite/"):
                    invite_value = parsed.path.rsplit("/", 1)[-1]
                    user = public_user_by_invite(conn, invite_value)
                    self.send_json(user if user else {"error": "Пользователь не найден"}, HTTPStatus.OK if user else HTTPStatus.NOT_FOUND)
                elif parsed.path == "/api/users/search":
                    self.send_json(search_users(conn, params))
                elif parsed.path.startswith("/api/users/") and parsed.path.endswith("/public"):
                    user_id = int(parsed.path.split("/")[-2])
                    user = public_user(conn, user_id)
                    self.send_json(user if user else {"error": "Пользователь не найден"}, HTTPStatus.OK if user else HTTPStatus.NOT_FOUND)
                elif parsed.path.startswith("/api/users/") and parsed.path.endswith("/profile"):
                    user_id = int(parsed.path.split("/")[-2])
                    profile = get_profile(conn, user_id)
                    self.send_json(profile if profile else {"error": "Профиль не найден"}, HTTPStatus.OK if profile else HTTPStatus.NOT_FOUND)
                elif parsed.path == "/api/teams":
                    user_id = int(params.get("user_id", ["0"])[0] or 0)
                    if user_id:
                        rows = conn.execute(
                            """
                            SELECT t.* FROM teams t
                            JOIN team_members tm ON tm.team_id = t.id
                            WHERE tm.user_id = ?
                            ORDER BY t.name
                            """,
                            (user_id,),
                        ).fetchall()
                    else:
                        rows = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
                    self.send_json([row_to_dict(row) for row in rows])
                elif parsed.path.startswith("/api/teams/"):
                    team = get_team(conn, int(parsed.path.rsplit("/", 1)[-1]))
                    self.send_json(team if team else {"error": "Команда не найдена"}, HTTPStatus.OK if team else HTTPStatus.NOT_FOUND)
                elif parsed.path == "/api/events":
                    self.send_json(get_events(conn, params))
                elif parsed.path.startswith("/api/events/"):
                    user_id = int(params.get("user_id", ["0"])[0] or 0)
                    event = get_event(conn, int(parsed.path.rsplit("/", 1)[-1]), user_id)
                    self.send_json(event if event else {"error": "Событие не найдено"}, HTTPStatus.OK if event else HTTPStatus.NOT_FOUND)
                elif parsed.path == "/api/dashboard":
                    self.send_json(get_dashboard(conn, int(params.get("user_id", ["0"])[0] or 0)))
                elif parsed.path.startswith("/api/analytics/user/"):
                    user_id = int(parsed.path.rsplit("/", 1)[-1])
                    period = params.get("period", ["month"])[0]
                    self.send_json(get_user_analytics(conn, user_id, period))
                elif parsed.path.startswith("/api/analytics/team/"):
                    self.send_json(get_team_analytics(conn, int(parsed.path.rsplit("/", 1)[-1])))
                else:
                    self.send_json({"error": "Unknown endpoint"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return self.send_error(HTTPStatus.NOT_FOUND)
        try:
            payload = self.read_json()
            with connect() as conn:
                if parsed.path == "/api/register":
                    self.send_json(create_user(conn, payload), HTTPStatus.CREATED)
                elif parsed.path == "/api/events":
                    self.send_json(create_event(conn, payload), HTTPStatus.CREATED)
                elif parsed.path.startswith("/api/events/") and parsed.path.endswith("/status"):
                    event_id = int(parsed.path.split("/")[-2])
                    user_id = int(payload.get("user_id", 0))
                    status = payload.get("status", "planned")
                    if status not in PARTICIPATION_STATUSES:
                        raise ValueError("Неизвестный статус участия.")
                    stamp = now_iso()
                    conn.execute(
                        """
                        INSERT INTO user_events(user_id, event_id, status, notes, participation_marked_at, source, updated_at)
                        VALUES (?, ?, ?, COALESCE((SELECT notes FROM user_events WHERE user_id=? AND event_id=?), ''), ?, 'self', ?)
                        ON CONFLICT(user_id, event_id) DO UPDATE SET
                            status=excluded.status,
                            participation_marked_at=excluded.participation_marked_at,
                            updated_at=excluded.updated_at
                        """,
                        (user_id, event_id, status, user_id, event_id, stamp, stamp),
                    )
                    self.send_json(get_event(conn, event_id, user_id))
                elif parsed.path.startswith("/api/events/") and parsed.path.endswith("/notes"):
                    event_id = int(parsed.path.split("/")[-2])
                    user_id = int(payload.get("user_id", 0))
                    stamp = now_iso()
                    conn.execute(
                        """
                        INSERT INTO user_events(user_id, event_id, status, notes, participation_marked_at, source, updated_at)
                        VALUES (?, ?, 'interested', ?, ?, 'self', ?)
                        ON CONFLICT(user_id, event_id) DO UPDATE SET notes=excluded.notes, updated_at=excluded.updated_at
                        """,
                        (user_id, event_id, payload.get("notes", ""), stamp, stamp),
                    )
                    self.send_json(get_event(conn, event_id, user_id))
                elif parsed.path.startswith("/api/events/") and parsed.path.endswith("/comments"):
                    event_id = int(parsed.path.split("/")[-2])
                    conn.execute(
                        "INSERT INTO comments(event_id, user_id, body, created_at) VALUES (?, ?, ?, ?)",
                        (event_id, int(payload.get("user_id", 0)), payload.get("body", "").strip(), now_iso()),
                    )
                    self.send_json(get_event(conn, event_id, int(payload.get("user_id", 0))), HTTPStatus.CREATED)
                elif parsed.path == "/api/teams":
                    name = payload.get("name", "").strip()
                    if len(name) < 2:
                        raise ValueError("Название команды должно содержать минимум 2 символа.")
                    user_id = int(payload.get("created_by", 0))
                    cur = conn.execute(
                        "INSERT INTO teams(name, created_by, invite_token, created_at) VALUES (?, ?, ?, ?)",
                        (name, user_id, token(), now_iso()),
                    )
                    conn.execute(
                        "INSERT INTO team_members(team_id, user_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
                        (cur.lastrowid, user_id, now_iso()),
                    )
                    self.send_json(get_team(conn, cur.lastrowid), HTTPStatus.CREATED)
                elif parsed.path == "/api/friends/request":
                    self.send_json(request_friend(conn, int(payload["requester_id"]), int(payload["target_id"])), HTTPStatus.CREATED)
                elif parsed.path == "/api/friends/respond":
                    requester_id = int(payload["requester_id"])
                    addressee_id = int(payload["addressee_id"])
                    status = payload.get("status", "accepted")
                    if status not in ("accepted", "declined"):
                        raise ValueError("Неизвестный статус приглашения.")
                    conn.execute(
                        "UPDATE friendships SET status=?, responded_at=? WHERE requester_id=? AND addressee_id=?",
                        (status, now_iso(), requester_id, addressee_id),
                    )
                    self.send_json({"status": status})
                elif parsed.path == "/api/team-invites":
                    team_id = int(payload["team_id"])
                    invited_user_id = int(payload["invited_user_id"])
                    invited_by = int(payload["invited_by"])
                    conn.execute(
                        """
                        INSERT INTO team_invitations(team_id, invited_user_id, invited_by, status, created_at)
                        VALUES (?, ?, ?, 'pending', ?)
                        """,
                        (team_id, invited_user_id, invited_by, now_iso()),
                    )
                    self.send_json({"status": "pending"}, HTTPStatus.CREATED)
                elif parsed.path == "/api/team-invites/respond":
                    invite_id = int(payload["invite_id"])
                    status = payload.get("status", "accepted")
                    if status not in ("accepted", "declined"):
                        raise ValueError("Неизвестный статус приглашения.")
                    invite = conn.execute("SELECT * FROM team_invitations WHERE id = ?", (invite_id,)).fetchone()
                    if not invite:
                        raise ValueError("Приглашение не найдено.")
                    conn.execute(
                        "UPDATE team_invitations SET status=?, responded_at=? WHERE id=?",
                        (status, now_iso(), invite_id),
                    )
                    if status == "accepted":
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO team_members(team_id, user_id, role, joined_at)
                            VALUES (?, ?, 'member', ?)
                            """,
                            (invite["team_id"], invite["invited_user_id"], now_iso()),
                        )
                    self.send_json({"status": status})
                else:
                    self.send_json({"error": "Unknown endpoint"}, HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main() -> None:
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("EventLog MVP is running at http://127.0.0.1:8000")
    server.serve_forever()


if __name__ == "__main__":
    main()
