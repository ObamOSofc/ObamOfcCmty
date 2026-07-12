import os
import secrets
import sqlite3
import hashlib
import binascii
from datetime import datetime, timezone

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from PIL import Image
from streamlit_cookies_manager import EncryptedCookieManager

# ----------------------------------------------------------------------------
# Paths / setup
# ----------------------------------------------------------------------------
os.makedirs("assets/avatars", exist_ok=True)
os.makedirs("assets/uploads", exist_ok=True)

st.set_page_config(page_title="ObamOfcCmty", layout="wide")

cookies = EncryptedCookieManager(
    prefix="obamofccmty/",
    password=os.environ.get("COOKIES_SECRET_KEY", "a_very_secure_and_long_secret_key_here_123456789")
)
if not cookies.ready():
    st.stop()

DB_FILE = "database.db"
MAX_DB_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB

# Default site settings. Admins can change all of these at runtime from the
# Admin Dashboard -> "Site Settings" tab. These are only used the first time
# the app boots (to seed the settings table).
SETTINGS_DEFAULTS = {
    "site_name": "ObamOfcCmty",
    "primary_color": "#ff4b4b",
    "welcome_message": "Welcome to the community! Post something, join a server, or say hi in DMs.",
    "announcement": "",
    "max_upload_mb": "25",
    "allowed_file_types": "png,jpg,jpeg,mp4,mov,avi",
    "registration_open": "1",
    "enable_feed": "1",
    "enable_servers": "1",
    "enable_dms": "1",
    "show_tiktok_mode": "1",
}


# ----------------------------------------------------------------------------
# DB maintenance
# ----------------------------------------------------------------------------
def cleanup_old_db_data():
    """Prunes old rows if the SQLite database exceeds the size threshold."""
    if os.path.exists(DB_FILE) and os.path.getsize(DB_FILE) > MAX_DB_SIZE:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute(
                "DELETE FROM channel_messages WHERE id IN (SELECT id FROM channel_messages ORDER BY id ASC LIMIT 200)")
            c.execute("DELETE FROM dms WHERE id IN (SELECT id FROM dms ORDER BY id ASC LIMIT 200)")
            c.execute("DELETE FROM posts WHERE id IN (SELECT id FROM posts ORDER BY id ASC LIMIT 50)")
            conn.commit()


def _add_column_if_missing(c, table, column_def):
    col_name = column_def.split()[0]
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
    except sqlite3.OperationalError:
        pass


def init_db():
    cleanup_old_db_data()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY, password TEXT, salt TEXT, bio TEXT, avatar_path TEXT,
                        role TEXT DEFAULT 'user', last_ip TEXT, last_device TEXT, created_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS follows (
                        follower TEXT, following TEXT, created_at TEXT, PRIMARY KEY(follower, following))''')
        c.execute('''CREATE TABLE IF NOT EXISTS posts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, author TEXT, text TEXT, file_path TEXT,
                        file_type TEXT, reply_to INTEGER DEFAULT NULL, created_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS likes (
                        post_id INTEGER, username TEXT, PRIMARY KEY(post_id, username))''')
        c.execute('''CREATE TABLE IF NOT EXISTS servers (
                        name TEXT PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS channels (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, server_name TEXT, name TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS channel_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER, user TEXT, text TEXT,
                        reply_to INTEGER DEFAULT NULL, file_path TEXT, file_type TEXT, created_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS dms (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, user_from TEXT, user_to TEXT, text TEXT,
                        reply_to INTEGER DEFAULT NULL, file_path TEXT, file_type TEXT, created_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS msg_reactions (
                        message_id INTEGER, msg_type TEXT, username TEXT, emoji TEXT,
                        PRIMARY KEY(message_id, msg_type, username, emoji))''')
        c.execute('''CREATE TABLE IF NOT EXISTS notifications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, recipient TEXT, sender TEXT, type TEXT,
                        content TEXT, ref_type TEXT, ref_id INTEGER, is_read INTEGER DEFAULT 0, created_at TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY, value TEXT)''')

        # Migrations for older DBs created before these columns existed.
        migrations = [
            ("users", "salt TEXT"),
            ("users", "avatar_path TEXT"),
            ("users", "created_at TEXT"),
            ("posts", "file_path TEXT"),
            ("posts", "file_type TEXT"),
            ("posts", "reply_to INTEGER DEFAULT NULL"),
            ("posts", "created_at TEXT"),
            ("channel_messages", "reply_to INTEGER DEFAULT NULL"),
            ("channel_messages", "file_path TEXT"),
            ("channel_messages", "file_type TEXT"),
            ("channel_messages", "created_at TEXT"),
            ("dms", "reply_to INTEGER DEFAULT NULL"),
            ("dms", "file_path TEXT"),
            ("dms", "file_type TEXT"),
            ("dms", "created_at TEXT"),
            ("follows", "created_at TEXT"),
            ("notifications", "content TEXT"),
            ("notifications", "ref_type TEXT"),
            ("notifications", "ref_id INTEGER"),
            ("notifications", "created_at TEXT"),
        ]
        for table, column in migrations:
            _add_column_if_missing(c, table, column)

        # Seed default site settings (won't overwrite ones an admin already changed).
        for key, value in SETTINGS_DEFAULTS.items():
            c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

        # Bootstrap the superuser account. Credentials come from environment
        # variables instead of being hardcoded in source, and a random
        # password is generated (and printed to server logs once) if none is
        # configured, so nobody who reads this file gets a free admin login.
        admin_username = os.environ.get("ADMIN_USERNAME", "ArchPenguin")
        c.execute("SELECT username FROM users WHERE username = ?", (admin_username,))
        if not c.fetchone():
            admin_password = os.environ.get("ADMIN_PASSWORD")
            if not admin_password:
                admin_password = secrets.token_urlsafe(12)
                print(f"[SETUP] No ADMIN_PASSWORD env var set. Generated a one-time password "
                      f"for '{admin_username}': {admin_password}\n"
                      f"        Set ADMIN_PASSWORD (and optionally ADMIN_USERNAME) to control this yourself.")
            salt = secrets.token_hex(16)
            pw_hash = hash_password(admin_password, salt)
            c.execute("""INSERT INTO users (username, password, salt, bio, role, created_at)
                         VALUES (?, ?, ?, ?, ?, ?)""",
                      (admin_username, pw_hash, salt, "System Administrator", "superuser", _now()))

        c.execute("INSERT OR IGNORE INTO servers (name) VALUES (?)", ("Global Server",))
        c.execute("SELECT id FROM channels WHERE server_name = ? AND name = ?", ("Global Server", "general"))
        if not c.fetchone():
            c.execute("INSERT INTO channels (server_name, name) VALUES (?, ?)", ("Global Server", "general"))
        conn.commit()


def query_db(query, args=(), one=False, commit=False):
    cleanup_old_db_data()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(query, args)
        if commit:
            conn.commit()
            rv = c.lastrowid if query.strip().upper().startswith("INSERT") else None
        else:
            rv = c.fetchall()
    return (rv[0] if rv else None) if one else rv


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def _now():
    return datetime.now(timezone.utc).isoformat()


def time_ago(iso_str):
    if not iso_str:
        return ""
    try:
        then = datetime.fromisoformat(iso_str)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - then
        secs = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            return f"{secs // 60}m ago"
        if secs < 86400:
            return f"{secs // 3600}h ago"
        return f"{secs // 86400}d ago"
    except Exception:
        return ""


def snippet(text, length=60):
    if not text:
        return ""
    text = str(text)
    return text if len(text) <= length else text[:length].rstrip() + "..."


def hash_password(password, salt):
    """PBKDF2-HMAC-SHA256 with a per-user salt (100k iterations)."""
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return binascii.hexlify(dk).decode()


def verify_password(username, password):
    """Checks a password, transparently upgrading any legacy unsalted
    SHA-256 hashes (from the old version of this app) to salted PBKDF2 on
    successful login."""
    row = query_db("SELECT password, salt FROM users WHERE username = ?", (username,), one=True)
    if not row:
        return False
    stored_hash, salt = row
    if salt:
        return stored_hash == hash_password(password, salt)
    # Legacy path: old plain sha256(password) with no salt.
    legacy_hash = hashlib.sha256(password.encode()).hexdigest()
    if stored_hash == legacy_hash:
        new_salt = secrets.token_hex(16)
        new_hash = hash_password(password, new_salt)
        query_db("UPDATE users SET password = ?, salt = ? WHERE username = ?",
                 (new_hash, new_salt, username), commit=True)
        return True
    return False


def get_client_info():
    ctx = st.context
    headers = ctx.headers
    ip = headers.get("X-Forwarded-For", headers.get("Remote-Addr", "127.0.0.1")).split(",")[0].strip()
    user_agent = headers.get("User-Agent", "Unknown Device")
    return ip, user_agent


# ----------------------------------------------------------------------------
# Site settings (admin-editable, no code changes required)
# ----------------------------------------------------------------------------
def get_settings():
    if "site_settings" not in st.session_state:
        rows = query_db("SELECT key, value FROM settings")
        settings = dict(SETTINGS_DEFAULTS)
        settings.update({k: v for k, v in rows})
        st.session_state.site_settings = settings
    return st.session_state.site_settings


def set_setting(key, value):
    query_db("INSERT INTO settings (key, value) VALUES (?, ?) "
              "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)), commit=True)
    st.session_state.pop("site_settings", None)


def setting_bool(settings, key):
    return str(settings.get(key, "0")) == "1"


def apply_theme(settings):
    color = settings.get("primary_color") or "#ff4b4b"
    st.markdown(f"""
        <style>
        :root {{ --accent-color: {color}; }}
        div[data-testid="stSidebar"] h1 {{ color: {color}; }}
        .accent-badge {{
            display:inline-block; padding:2px 8px; border-radius:999px;
            background:{color}22; color:{color}; font-size:0.8em; font-weight:600;
        }}
        .announcement-banner {{
            background:{color}18; border-left:4px solid {color};
            padding:10px 14px; border-radius:6px; margin-bottom:14px;
        }}
        </style>
    """, unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Chat autoscroll (Discord-style "jump to newest message")
# ----------------------------------------------------------------------------
def autoscroll_chat(container_key):
    """Scrolls a st.container(key=container_key, height=...) to its bottom.
    Relies on Streamlit's 'st-key-<key>' class marker; if a future Streamlit
    version renames that class this degrades gracefully to a no-op."""
    js = f"""
    <script>
    (function() {{
        function scrollDown() {{
            try {{
                const doc = window.parent.document;
                const els = doc.querySelectorAll('[class*="st-key-{container_key}"]');
                els.forEach(function(el) {{ el.scrollTop = el.scrollHeight; }});
            }} catch (e) {{}}
        }}
        [50, 150, 350, 700].forEach(function(t) {{ setTimeout(scrollDown, t); }});
    }})();
    </script>
    """
    components.html(js, height=0)


# ----------------------------------------------------------------------------
# Notifications
# ----------------------------------------------------------------------------
def notify(recipient, sender, n_type, content=None, ref_type=None, ref_id=None):
    if recipient == sender:
        return
    query_db("""INSERT INTO notifications (recipient, sender, type, content, ref_type, ref_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
             (recipient, sender, n_type, content, ref_type, ref_id, _now()), commit=True)


# ----------------------------------------------------------------------------
# Follow system
# ----------------------------------------------------------------------------
def is_following(follower, following):
    if not follower or not following:
        return False
    row = query_db("SELECT 1 FROM follows WHERE follower = ? AND following = ?", (follower, following), one=True)
    return bool(row)


def follow_counts(username):
    followers = query_db("SELECT COUNT(*) FROM follows WHERE following = ?", (username,), one=True)[0]
    following = query_db("SELECT COUNT(*) FROM follows WHERE follower = ?", (username,), one=True)[0]
    return followers, following


def toggle_follow(current_user, target_user):
    if is_following(current_user, target_user):
        query_db("DELETE FROM follows WHERE follower = ? AND following = ?", (current_user, target_user), commit=True)
    else:
        query_db("INSERT OR IGNORE INTO follows (follower, following, created_at) VALUES (?, ?, ?)",
                 (current_user, target_user, _now()), commit=True)
        notify(target_user, current_user, "follow", content=f"{current_user} started following you.")


# ----------------------------------------------------------------------------
# File uploads
# ----------------------------------------------------------------------------
def save_uploaded_file(uploaded_file, settings):
    if uploaded_file is None:
        return None, None

    allowed = [ext.strip().lower() for ext in settings.get("allowed_file_types", "").split(",") if ext.strip()]
    file_ext = uploaded_file.name.split(".")[-1].lower()
    if allowed and file_ext not in allowed:
        st.error(f"File type '.{file_ext}' is not allowed. Allowed types: {', '.join(allowed)}")
        return None, None

    max_mb = float(settings.get("max_upload_mb", "25") or 25)
    size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)
    if size_mb > max_mb:
        st.error(f"File is {size_mb:.1f} MB, which exceeds the {max_mb:.0f} MB limit set by admins.")
        return None, None

    try:
        file_hash = hashlib.md5(uploaded_file.getvalue()).hexdigest()
        save_path = f"assets/uploads/{file_hash}.{file_ext}"
        with open(save_path, "wb") as f:
            f.write(uploaded_file.getvalue())
        mime = uploaded_file.type or ""
        file_type = "image" if "image" in mime else "video"
        return save_path, file_type
    except OSError as e:
        st.error(f"Could not save the uploaded file: {e}")
        return None, None


def render_media(file_path, file_type, width=400):
    if file_path and os.path.exists(file_path):
        if file_type == "image":
            st.image(file_path, width=width)
        else:
            st.video(file_path)


def render_emoji_picker(key_prefix):
    emojis = ["", "😀", "😂", "🔥", "👍", "❤️", "👀", "🚀", "👑", "⚠️"]
    chosen_emoji = st.selectbox("Select an Emoji to Copy", emojis, key=f"picker_{key_prefix}")
    return chosen_emoji if chosen_emoji != "" else None


# ----------------------------------------------------------------------------
# Session state initialization
# ----------------------------------------------------------------------------
init_db()

if "user" not in st.session_state:
    st.session_state.user = cookies.get("auth_user") or None
if "current_view" not in st.session_state:
    st.session_state.current_view = "Feed"
if "active_server" not in st.session_state:
    st.session_state.active_server = "Global Server"
if "active_channel_id" not in st.session_state:
    ch = query_db("SELECT id FROM channels WHERE server_name = ? AND name = ?", ("Global Server", "general"), one=True)
    st.session_state.active_channel_id = ch[0] if ch else None
if "active_dm_target" not in st.session_state:
    st.session_state.active_dm_target = None
if "selected_profile" not in st.session_state:
    st.session_state.selected_profile = None
if "reply_target_id" not in st.session_state:
    st.session_state.reply_target_id = None
if "feed_following_only" not in st.session_state:
    st.session_state.feed_following_only = False

settings = get_settings()
apply_theme(settings)

user_role_data = query_db("SELECT role FROM users WHERE username = ?", (st.session_state.user,),
                          one=True) if st.session_state.user else None
is_admin_user = bool(user_role_data and user_role_data[0] in ["admin", "superuser"])


# ----------------------------------------------------------------------------
# Sidebar
# ----------------------------------------------------------------------------
def render_sidebar():
    st.sidebar.title(settings.get("site_name", "ObamOfcCmty"))
    if os.path.exists("logo.png"):
        st.sidebar.image(Image.open("logo.png"), use_container_width=True)

    st.sidebar.write(f"Logged in as: **{st.session_state.user}**")
    if st.sidebar.button("Log Out", use_container_width=True):
        cookies["auth_user"] = ""
        cookies.save()
        st.session_state.user = None
        st.rerun()

    st.sidebar.markdown("---")

    unread = query_db("SELECT COUNT(*) FROM notifications WHERE recipient = ? AND is_read = 0",
                      (st.session_state.user,), one=True)
    unread_count = unread[0] if unread else 0
    badge = f" ({'9+' if unread_count > 9 else unread_count})" if unread_count > 0 else ""

    if unread_count > 0:
        st.sidebar.markdown("""
            <style>
            div[data-testid="stSidebar"] button:has(div:contains("Notifications")) {
                background-color: #3b0d0d !important;
                border: 1px solid #ff4b4b !important;
                box-shadow: 0 0 10px #ff4b4b;
                color: #ff4b4b !important;
            }
            </style>
        """, unsafe_allow_html=True)

    views = []
    if setting_bool(settings, "enable_feed"):
        views.append("Feed")
    if setting_bool(settings, "enable_servers"):
        views.append("Servers")
    if setting_bool(settings, "enable_dms"):
        views.append("Direct Messages")
    views.append(f"Notifications{badge}")
    views.append("Profile Settings")
    if is_admin_user:
        views.append("Admin Dashboard")

    for view in views:
        clean_view_name = "Notifications" if "Notifications" in view else view
        if st.sidebar.button(view, use_container_width=True, key=f"sidebar_nav_{clean_view_name}"):
            st.session_state.current_view = clean_view_name
            st.session_state.selected_profile = None
            st.session_state.reply_target_id = None
            st.rerun()

    followers_n, following_n = follow_counts(st.session_state.user)
    st.sidebar.markdown("---")
    st.sidebar.caption(f"👥 {followers_n} followers · {following_n} following")


# ----------------------------------------------------------------------------
# Profile card (used everywhere a profile is opened)
# ----------------------------------------------------------------------------
def render_profile_card():
    profile_user = st.session_state.selected_profile
    st.markdown(f"## Profile: {profile_user}")
    p_info = query_db("SELECT bio, avatar_path, role, created_at FROM users WHERE username = ?",
                      (profile_user,), one=True)
    if not p_info:
        st.error("This user no longer exists.")
        if st.button("Close"):
            st.session_state.selected_profile = None
            st.rerun()
        return

    if st.session_state.user and profile_user != st.session_state.user:
        notify(profile_user, st.session_state.user, "profile_view",
               content=f"{st.session_state.user} viewed your profile.")

    col_avatar, col_info, col_actions = st.columns([1, 2, 1])
    with col_avatar:
        if p_info[1] and os.path.exists(p_info[1]):
            st.image(p_info[1], width=120)
        else:
            st.markdown("### 👤")

    with col_info:
        st.markdown(f"**Role:** <span class='accent-badge'>{p_info[2].upper()}</span>", unsafe_allow_html=True)
        st.write(f"**Bio:** {p_info[0] if p_info[0] else '*No bio written yet.*'}")
        followers_n, following_n = follow_counts(profile_user)
        post_count = query_db("SELECT COUNT(*) FROM posts WHERE author = ?", (profile_user,), one=True)[0]
        st.caption(f"📝 {post_count} posts · 👥 {followers_n} followers · ➡️ {following_n} following")
        if p_info[3]:
            st.caption(f"Joined {time_ago(p_info[3])}")

    with col_actions:
        if profile_user != st.session_state.user:
            following_now = is_following(st.session_state.user, profile_user)
            btn_label = "✓ Following" if following_now else "+ Follow"
            if st.button(btn_label, key=f"follow_btn_{profile_user}", use_container_width=True):
                toggle_follow(st.session_state.user, profile_user)
                st.rerun()
            if st.button("Message", key=f"msg_from_profile_{profile_user}", use_container_width=True):
                st.session_state.active_dm_target = profile_user
                st.session_state.selected_profile = None
                st.session_state.current_view = "Direct Messages"
                st.rerun()
        if st.button("Close Profile View", key="close_profile_card", use_container_width=True):
            st.session_state.selected_profile = None
            st.rerun()

    with st.expander(f"Recent posts by {profile_user}"):
        recent_posts = query_db(
            "SELECT id, text, file_path, file_type, created_at FROM posts WHERE author = ? ORDER BY id DESC LIMIT 5",
            (profile_user,))
        if not recent_posts:
            st.caption("No posts yet.")
        for rp_id, rp_text, rp_file, rp_type, rp_created in recent_posts:
            st.markdown(f"*{time_ago(rp_created)}*")
            if rp_text:
                st.write(rp_text)
            render_media(rp_file, rp_type, width=250)
            st.markdown("---")

    st.markdown("---")


# ----------------------------------------------------------------------------
# Auth screens
# ----------------------------------------------------------------------------
def render_auth_screens():
    st.title(settings.get("site_name", "ObamOfcCmty"))
    if settings.get("welcome_message"):
        st.caption(settings["welcome_message"])

    tab_labels = ["Login"] + (["Register"] if setting_bool(settings, "registration_open") else [])
    tabs = st.tabs(tab_labels)

    with tabs[0]:
        username_input = st.text_input("Username", key="login_user")
        password_input = st.text_input("Password", type="password", key="login_pass")
        if st.button("Enter"):
            if verify_password(username_input, password_input):
                ip, ua = get_client_info()
                query_db("UPDATE users SET last_ip = ?, last_device = ? WHERE username = ?", (ip, ua, username_input),
                         commit=True)
                cookies["auth_user"] = username_input
                cookies.save()
                st.session_state.user = username_input
                st.rerun()
            else:
                st.error("Invalid credentials.")

    if len(tabs) > 1:
        with tabs[1]:
            reg_user = st.text_input("Choose Username", key="reg_user")
            reg_pass = st.text_input("Choose Password", type="password", key="reg_pass")
            if st.button("Create Account"):
                if not reg_user.strip() or not reg_pass.strip():
                    st.error("Fields cannot be empty.")
                elif len(reg_pass) < 6:
                    st.error("Password should be at least 6 characters.")
                elif query_db("SELECT username FROM users WHERE username = ?", (reg_user,), one=True):
                    st.error("Username taken.")
                else:
                    ip, ua = get_client_info()
                    salt = secrets.token_hex(16)
                    pw_hash = hash_password(reg_pass, salt)
                    query_db("""INSERT INTO users (username, password, salt, bio, last_ip, last_device, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                             (reg_user, pw_hash, salt, "", ip, ua, _now()), commit=True)
                    st.success("Account created. Log in now.")
    else:
        st.info("Registration is currently closed by administrators.")


# ----------------------------------------------------------------------------
# Feed
# ----------------------------------------------------------------------------
def render_feed():
    st.header("Feed Portal")

    with st.expander("🔎 Discover people to follow"):
        search_q = st.text_input("Search by username", key="discover_search")
        if search_q.strip():
            matches = query_db("SELECT username FROM users WHERE username LIKE ? AND username != ? LIMIT 10",
                               (f"%{search_q.strip()}%", st.session_state.user))
            for (m_user,) in matches:
                mc1, mc2, mc3 = st.columns([2, 1, 1])
                mc1.write(f"**{m_user}**")
                following_now = is_following(st.session_state.user, m_user)
                if mc2.button("✓ Following" if following_now else "+ Follow", key=f"disc_follow_{m_user}"):
                    toggle_follow(st.session_state.user, m_user)
                    st.rerun()
                if mc3.button("View", key=f"disc_view_{m_user}"):
                    st.session_state.selected_profile = m_user
                    st.rerun()

    mode_options = ["Standard Stream", "TikTok Scroll Mode"] if setting_bool(settings, "show_tiktok_mode") \
        else ["Standard Stream"]
    mode = st.radio("Display Layout Mode", mode_options, horizontal=True)
    st.session_state.feed_following_only = st.checkbox("Show only people I follow",
                                                       value=st.session_state.feed_following_only)

    if st.session_state.reply_target_id:
        st.warning(f"Replying to Feed Post ID: {st.session_state.reply_target_id}")
        if st.button("Cancel Reply"):
            st.session_state.reply_target_id = None
            st.rerun()

    with st.form("new_post", clear_on_submit=True):
        post_text = st.text_area("What is happening?")
        uploaded_file = st.file_uploader("Upload Image or Video Media",
                                         type=[t.strip() for t in settings["allowed_file_types"].split(",")],
                                         key="feed_upload")
        emoji_picked = render_emoji_picker("feed_post")
        if emoji_picked:
            st.info(f"Selected: {emoji_picked} (Copy-paste this into your text)")

        if st.form_submit_button("Publish Post"):
            if post_text.strip() or uploaded_file:
                f_path, f_type = save_uploaded_file(uploaded_file, settings)
                if uploaded_file and not f_path:
                    st.stop()
                query_db("""INSERT INTO posts (author, text, file_path, file_type, reply_to, created_at)
                            VALUES (?, ?, ?, ?, ?, ?)""",
                         (st.session_state.user, post_text, f_path, f_type, st.session_state.reply_target_id, _now()),
                         commit=True)
                st.session_state.reply_target_id = None
                st.rerun()

    if st.session_state.feed_following_only:
        posts = query_db("""SELECT id, author, text, file_path, file_type, reply_to, created_at FROM posts
                             WHERE author IN (SELECT following FROM follows WHERE follower = ?) OR author = ?
                             ORDER BY id DESC""", (st.session_state.user, st.session_state.user))
    else:
        posts = query_db("SELECT id, author, text, file_path, file_type, reply_to, created_at FROM posts ORDER BY id DESC")

    if mode == "TikTok Scroll Mode" and posts:
        if "tiktok_idx" not in st.session_state:
            st.session_state.tiktok_idx = 0
        st.session_state.tiktok_idx = min(max(0, st.session_state.tiktok_idx), len(posts) - 1)

        p_id, author, text, file_path, file_type, reply_to, created_at = posts[st.session_state.tiktok_idx]
        st.markdown(f"### Post {st.session_state.tiktok_idx + 1} of {len(posts)} · *{time_ago(created_at)}*")

        if reply_to:
            parent_post = query_db("SELECT author, text FROM posts WHERE id = ?", (reply_to,), one=True)
            if parent_post:
                st.caption(f"↳ Replying to @{parent_post[0]}: *{snippet(parent_post[1], 40)}*")

        if st.button(f"👤 View {author}'s Full Profile", key=f"view_prof_tt_{p_id}"):
            st.session_state.selected_profile = author
            st.rerun()

        if text:
            st.write(text)
        render_media(file_path, file_type, width=600)

        c1, c2 = st.columns(2)
        if c1.button("◀ Previous", use_container_width=True) and st.session_state.tiktok_idx > 0:
            st.session_state.tiktok_idx -= 1
            st.rerun()
        if c2.button("Next ▶", use_container_width=True) and st.session_state.tiktok_idx < len(posts) - 1:
            st.session_state.tiktok_idx += 1
            st.rerun()
    else:
        if not posts:
            st.info("Nothing here yet." if not st.session_state.feed_following_only else
                     "You're not following anyone with posts yet, or nobody has posted. Try Discover above.")
        for p_id, author, text, file_path, file_type, reply_to, created_at in posts:
            if reply_to:
                parent_post = query_db("SELECT author, text FROM posts WHERE id = ?", (reply_to,), one=True)
                if parent_post:
                    st.caption(f"↳ Replying to @{parent_post[0]}: *{snippet(parent_post[1], 40)}*")

            col_author, col_view_p = st.columns([3, 1])
            with col_author:
                st.markdown(f"**{author}**  ·  *{time_ago(created_at)}*")
            with col_view_p:
                if st.button("View Profile", key=f"vp_{p_id}"):
                    st.session_state.selected_profile = author
                    st.rerun()

            if text:
                st.write(text)
            render_media(file_path, file_type)

            likes = query_db("SELECT username FROM likes WHERE post_id = ?", (p_id,))
            is_liked = any(l[0] == st.session_state.user for l in likes)
            like_label = f"Liked ({len(likes)})" if is_liked else f"Like ({len(likes)})"

            col_lk, col_rep, col_del = st.columns([2, 2, 6])
            with col_lk:
                if st.button(like_label, key=f"like_{p_id}"):
                    if is_liked:
                        query_db("DELETE FROM likes WHERE post_id = ? AND username = ?",
                                 (p_id, st.session_state.user), commit=True)
                    else:
                        query_db("INSERT INTO likes (post_id, username) VALUES (?, ?)",
                                 (p_id, st.session_state.user), commit=True)
                        notify(author, st.session_state.user, "like",
                               content=f"{st.session_state.user} liked your post: \"{snippet(text, 50)}\"",
                               ref_type="post", ref_id=p_id)
                    st.rerun()
            with col_rep:
                if st.button("Reply ⮪", key=f"rep_feed_{p_id}"):
                    st.session_state.reply_target_id = p_id
                    st.rerun()
            with col_del:
                if is_admin_user:
                    if st.button("Delete Post", key=f"del_post_{p_id}"):
                        query_db("DELETE FROM posts WHERE id = ?", (p_id,), commit=True)
                        query_db("DELETE FROM likes WHERE post_id = ?", (p_id,), commit=True)
                        st.rerun()
            st.markdown("---")


# ----------------------------------------------------------------------------
# Servers
# ----------------------------------------------------------------------------
def render_servers():
    st.header("Guild Servers")
    col1, col2 = st.columns([1, 3])

    with col1:
        st.subheader("Servers List")
        new_server = st.text_input("Create Server")
        if st.button("Confirm Server Setup"):
            if new_server.strip() and not query_db("SELECT name FROM servers WHERE name = ?", (new_server,),
                                                   one=True):
                query_db("INSERT INTO servers (name) VALUES (?)", (new_server,), commit=True)
                query_db("INSERT INTO channels (server_name, name) VALUES (?, ?)", (new_server, "general"),
                         commit=True)
                st.rerun()

        st.markdown("---")
        servers = query_db("SELECT name FROM servers")
        for server in servers:
            if st.button(f"📁 {server[0]}", key=f"srv_{server[0]}", use_container_width=True):
                st.session_state.active_server = server[0]
                first_ch = query_db("SELECT id FROM channels WHERE server_name = ? LIMIT 1", (server[0],), one=True)
                st.session_state.active_channel_id = first_ch[0] if first_ch else None
                st.rerun()

    with col2:
        srv = st.session_state.active_server
        st.subheader(f"Active Hub: {srv}")
        ch_col, chat_col = st.columns([1, 2])

        with ch_col:
            st.write("**Text Channels**")
            new_ch = st.text_input("New Text Channel Name")
            if st.button("Add Channel Room"):
                if new_ch.strip() and not query_db("SELECT id FROM channels WHERE server_name = ? AND name = ?",
                                                   (srv, new_ch), one=True):
                    query_db("INSERT INTO channels (server_name, name) VALUES (?, ?)", (srv, new_ch), commit=True)
                    st.rerun()

            channels = query_db("SELECT id, name FROM channels WHERE server_name = ?", (srv,))
            for ch_id, ch_name in channels:
                if st.button(f"# {ch_name}", key=f"ch_{ch_id}", use_container_width=True):
                    st.session_state.active_channel_id = ch_id
                    st.rerun()

        with chat_col:
            ch_id = st.session_state.active_channel_id
            if ch_id:
                ch_info = query_db("SELECT name FROM channels WHERE id = ?", (ch_id,), one=True)
                st.write(f"### #{ch_info[0] if ch_info else ''}")

                if st.session_state.reply_target_id:
                    st.warning(f"Replying to Message ID: {st.session_state.reply_target_id}")
                    if st.button("Cancel Reply", key="cancel_srv_reply"):
                        st.session_state.reply_target_id = None
                        st.rerun()

                scroll_key = f"srv_scroll_{ch_id}"
                with st.container(height=450, border=True, key=scroll_key):
                    messages = query_db(
                        "SELECT id, user, text, reply_to, file_path, file_type, created_at FROM channel_messages "
                        "WHERE channel_id = ? ORDER BY id ASC", (ch_id,))
                    for msg_id, msg_user, msg_text, reply_to, file_path, file_type, created_at in messages:
                        reactions = query_db(
                            "SELECT emoji, COUNT(*) FROM msg_reactions WHERE message_id = ? AND msg_type = 'channel' GROUP BY emoji",
                            (msg_id,))
                        react_str = " ".join([f"{r[0]}{r[1]}" for r in reactions])

                        if reply_to:
                            parent_msg = query_db("SELECT user, text FROM channel_messages WHERE id = ?",
                                                  (reply_to,), one=True)
                            if parent_msg:
                                st.caption(f"↳ Replying to @{parent_msg[0]}: *{snippet(parent_msg[1], 30)}*")

                        col_msg, col_act = st.columns([3, 2])
                        with col_msg:
                            if st.button(f"👤 {msg_user}", key=f"user_profile_link_{msg_id}"):
                                st.session_state.selected_profile = msg_user
                                st.rerun()
                            st.caption(time_ago(created_at))
                            st.markdown(f"{msg_text}  \n*{react_str}*")
                            render_media(file_path, file_type, width=250)

                        with col_act:
                            b_rep, b_reac, b_del = st.columns(3)
                            if b_rep.button("⮪", key=f"rep_ch_{msg_id}", help="Reply"):
                                st.session_state.reply_target_id = msg_id
                                st.rerun()
                            if b_reac.button("👍", key=f"react_ch_{msg_id}"):
                                query_db(
                                    "INSERT OR IGNORE INTO msg_reactions (message_id, msg_type, username, emoji) VALUES (?, 'channel', ?, '👍')",
                                    (msg_id, st.session_state.user), commit=True)
                                notify(msg_user, st.session_state.user, "reaction",
                                       content=f"{st.session_state.user} reacted 👍 to: \"{snippet(msg_text, 40)}\"",
                                       ref_type="channel_message", ref_id=msg_id)
                                st.rerun()
                            if is_admin_user and b_del.button("🗑️", key=f"del_ch_{msg_id}"):
                                query_db("DELETE FROM channel_messages WHERE id = ?", (msg_id,), commit=True)
                                st.rerun()
                autoscroll_chat(scroll_key)

                with st.form("send_msg", clear_on_submit=True):
                    msg_text = st.text_input("Write Message")
                    srv_upload = st.file_uploader("Attach file",
                                                  type=[t.strip() for t in settings["allowed_file_types"].split(",")],
                                                  key="srv_upload")
                    if st.form_submit_button("Send"):
                        if msg_text.strip() or srv_upload:
                            f_path, f_type = save_uploaded_file(srv_upload, settings)
                            if srv_upload and not f_path:
                                st.stop()
                            query_db(
                                "INSERT INTO channel_messages (channel_id, user, text, reply_to, file_path, file_type, created_at) "
                                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                                (ch_id, st.session_state.user, msg_text, st.session_state.reply_target_id, f_path,
                                 f_type, _now()), commit=True)
                            if st.session_state.reply_target_id:
                                parent_user = query_db("SELECT user FROM channel_messages WHERE id = ?",
                                                       (st.session_state.reply_target_id,), one=True)
                                if parent_user:
                                    notify(parent_user[0], st.session_state.user, "reply",
                                           content=f"{st.session_state.user} replied: \"{snippet(msg_text, 50)}\"",
                                           ref_type="channel_message", ref_id=ch_id)
                            st.session_state.reply_target_id = None
                            st.rerun()


# ----------------------------------------------------------------------------
# Direct Messages
# ----------------------------------------------------------------------------
def render_dms():
    st.header("Direct Messaging Vault")

    active_dm_nodes = query_db(
        "SELECT DISTINCT user_to FROM dms WHERE user_from = ? UNION SELECT DISTINCT user_from FROM dms WHERE user_to = ?",
        (st.session_state.user, st.session_state.user))
    dm_list = [node[0] for node in active_dm_nodes if node[0] != st.session_state.user]

    col_dm_nav, col_dm_chat = st.columns([1, 2])

    with col_dm_nav:
        st.subheader("Conversations")
        for person in dm_list:
            if st.button(f"💬 {person}", key=f"dm_target_{person}", use_container_width=True):
                st.session_state.active_dm_target = person
                st.session_state.reply_target_id = None
                st.rerun()

        st.markdown("---")
        search_new_dm = st.text_input("Start New DM (Type Username)")
        if st.button("Open Inbox"):
            if search_new_dm.strip() and query_db("SELECT username FROM users WHERE username = ?",
                                                  (search_new_dm.strip(),), one=True):
                st.session_state.active_dm_target = search_new_dm.strip()
                st.session_state.reply_target_id = None
                st.rerun()
            else:
                st.error("User does not exist.")

    with col_dm_chat:
        target_user = st.session_state.active_dm_target
        if target_user:
            col_t_title, col_t_profile = st.columns([3, 1])
            with col_t_title:
                st.subheader(f"Chat Room: @{target_user}")
            with col_t_profile:
                if st.button("View Profile", key="view_target_dm_profile"):
                    st.session_state.selected_profile = target_user
                    st.rerun()

            if st.session_state.reply_target_id:
                st.warning(f"Replying to DM ID: {st.session_state.reply_target_id}")
                if st.button("Cancel Reply", key="cancel_dm_reply"):
                    st.session_state.reply_target_id = None
                    st.rerun()

            scroll_key = f"dm_scroll_{target_user}"
            with st.container(height=450, border=True, key=scroll_key):
                messages = query_db('''SELECT id, user_from, text, reply_to, file_path, file_type, created_at
                                           FROM dms
                                           WHERE (user_from = ? AND user_to = ?) OR (user_from = ? AND user_to = ?)
                                           ORDER BY id ASC''',
                                    (st.session_state.user, target_user, target_user, st.session_state.user))
                for msg_id, msg_from, msg_text, reply_to, file_path, file_type, created_at in messages:
                    if reply_to:
                        parent_dm = query_db("SELECT user_from, text FROM dms WHERE id = ?", (reply_to,), one=True)
                        if parent_dm:
                            st.caption(f"↳ Replying to @{parent_dm[0]}: *{snippet(parent_dm[1], 30)}*")

                    col_msg_txt, col_msg_act = st.columns([4, 1])
                    with col_msg_txt:
                        if st.button(f"👤 {msg_from}", key=f"dm_author_profile_{msg_id}"):
                            st.session_state.selected_profile = msg_from
                            st.rerun()
                        st.caption(time_ago(created_at))
                        st.markdown(f"{msg_text}")
                        render_media(file_path, file_type, width=250)
                    with col_msg_act:
                        if st.button("⮪", key=f"rep_dm_{msg_id}", help="Reply"):
                            st.session_state.reply_target_id = msg_id
                            st.rerun()
            autoscroll_chat(scroll_key)

            with st.form("dm_form", clear_on_submit=True):
                dm_text = st.text_input("Send Private Message")
                dm_upload = st.file_uploader("Attach file",
                                             type=[t.strip() for t in settings["allowed_file_types"].split(",")],
                                             key="dm_upload")
                if st.form_submit_button("Send DM"):
                    if dm_text.strip() or dm_upload:
                        f_path, f_type = save_uploaded_file(dm_upload, settings)
                        if dm_upload and not f_path:
                            st.stop()
                        query_db(
                            "INSERT INTO dms (user_from, user_to, text, reply_to, file_path, file_type, created_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (st.session_state.user, target_user, dm_text, st.session_state.reply_target_id, f_path,
                             f_type, _now()), commit=True)
                        notify(target_user, st.session_state.user, "dm",
                               content=f"{st.session_state.user}: \"{snippet(dm_text, 60)}\"",
                               ref_type="dm", ref_id=None)
                        st.session_state.reply_target_id = None
                        st.rerun()
        else:
            st.info("Select a contact from the tracker or search a username to begin a dialogue.")


# ----------------------------------------------------------------------------
# Profile Settings
# ----------------------------------------------------------------------------
def render_profile_settings():
    st.header("Profile Configurations")
    u_data = query_db("SELECT bio, avatar_path FROM users WHERE username = ?", (st.session_state.user,), one=True)

    if u_data and u_data[1] and os.path.exists(u_data[1]):
        st.image(u_data[1], width=100)

    new_bio = st.text_area("Update Bio Information", value=u_data[0] if u_data else "")
    avatar_file = st.file_uploader("Upload New Profile Picture", type=["png", "jpg", "jpeg"])

    if st.button("Commit Profile Changes"):
        av_path = u_data[1] if u_data else None
        if avatar_file:
            saved_path, _ = save_uploaded_file(avatar_file, settings)
            if saved_path:
                av_path = saved_path
        query_db("UPDATE users SET bio = ?, avatar_path = ? WHERE username = ?",
                 (new_bio, av_path, st.session_state.user), commit=True)
        st.success("Successfully written configurations to profile parameters.")
        st.rerun()

    st.markdown("---")
    st.subheader("Change Password")
    with st.form("change_pw_form"):
        cur_pw = st.text_input("Current Password", type="password")
        new_pw = st.text_input("New Password", type="password")
        if st.form_submit_button("Update Password"):
            if not verify_password(st.session_state.user, cur_pw):
                st.error("Current password is incorrect.")
            elif len(new_pw) < 6:
                st.error("New password should be at least 6 characters.")
            else:
                new_salt = secrets.token_hex(16)
                new_hash = hash_password(new_pw, new_salt)
                query_db("UPDATE users SET password = ?, salt = ? WHERE username = ?",
                         (new_hash, new_salt, st.session_state.user), commit=True)
                st.success("Password updated.")


# ----------------------------------------------------------------------------
# Admin Dashboard
# ----------------------------------------------------------------------------
def render_admin_dashboard():
    st.header("Admin Operations Control Center")
    tab_users, tab_settings, tab_stats = st.tabs(["User Management", "Site Settings", "Analytics"])

    with tab_users:
        cmd_user = st.text_input("Target User Profile")
        cmd_action = st.selectbox("Action", ["Promote to Admin", "Demote to User", "Delete Profile Data Entirely"])

        if st.button("Execute Action"):
            target_role = query_db("SELECT role FROM users WHERE username = ?", (cmd_user,), one=True)
            if not target_role:
                st.error("Target individual does not exist.")
            elif target_role[0] == "superuser":
                st.error("Superuser credentials cannot be mutated.")
            else:
                if cmd_action == "Promote to Admin":
                    query_db("UPDATE users SET role = 'admin' WHERE username = ?", (cmd_user,), commit=True)
                elif cmd_action == "Demote to User":
                    query_db("UPDATE users SET role = 'user' WHERE username = ?", (cmd_user,), commit=True)
                elif cmd_action == "Delete Profile Data Entirely":
                    query_db("DELETE FROM users WHERE username = ?", (cmd_user,), commit=True)
                    query_db("DELETE FROM follows WHERE follower = ? OR following = ?", (cmd_user, cmd_user), commit=True)
                st.success("Administrative operation completed successfully.")
                st.rerun()

        st.markdown("---")
        st.subheader("All Users")
        all_users = query_db("SELECT username, role, last_ip, last_device, created_at FROM users ORDER BY username")
        if all_users:
            df = pd.DataFrame(all_users, columns=["Username", "Role", "Last IP", "Last Device", "Joined"])
            st.dataframe(df, use_container_width=True)

    with tab_settings:
        st.subheader("Site Settings")
        st.caption("These changes apply instantly, site-wide, with no code changes or redeploys needed.")
        with st.form("site_settings_form"):
            site_name = st.text_input("Site Name", value=settings.get("site_name", ""))
            primary_color = st.color_picker("Primary Accent Color", value=settings.get("primary_color", "#ff4b4b"))
            welcome_message = st.text_area("Welcome Message (shown on login screen)",
                                           value=settings.get("welcome_message", ""))
            announcement = st.text_area("Site-wide Announcement Banner (leave blank to hide)",
                                        value=settings.get("announcement", ""))
            max_upload_mb = st.number_input("Max Upload Size (MB)", min_value=1, max_value=1024,
                                            value=int(float(settings.get("max_upload_mb", 25))))
            allowed_file_types = st.text_input("Allowed File Extensions (comma separated)",
                                               value=settings.get("allowed_file_types", ""))
            registration_open = st.checkbox("Allow new user registration",
                                            value=setting_bool(settings, "registration_open"))
            enable_feed = st.checkbox("Enable Feed tab", value=setting_bool(settings, "enable_feed"))
            enable_servers = st.checkbox("Enable Servers tab", value=setting_bool(settings, "enable_servers"))
            enable_dms = st.checkbox("Enable Direct Messages tab", value=setting_bool(settings, "enable_dms"))
            show_tiktok_mode = st.checkbox("Allow TikTok Scroll Mode on Feed",
                                           value=setting_bool(settings, "show_tiktok_mode"))

            if st.form_submit_button("Save Site Settings"):
                set_setting("site_name", site_name.strip() or "ObamOfcCmty")
                set_setting("primary_color", primary_color)
                set_setting("welcome_message", welcome_message)
                set_setting("announcement", announcement)
                set_setting("max_upload_mb", str(max_upload_mb))
                set_setting("allowed_file_types", allowed_file_types)
                set_setting("registration_open", "1" if registration_open else "0")
                set_setting("enable_feed", "1" if enable_feed else "0")
                set_setting("enable_servers", "1" if enable_servers else "0")
                set_setting("enable_dms", "1" if enable_dms else "0")
                set_setting("show_tiktok_mode", "1" if show_tiktok_mode else "0")
                st.success("Site settings updated.")
                st.rerun()

    with tab_stats:
        st.subheader("Platform Analytics")
        n_users = query_db("SELECT COUNT(*) FROM users", one=True)[0]
        n_posts = query_db("SELECT COUNT(*) FROM posts", one=True)[0]
        n_channel_msgs = query_db("SELECT COUNT(*) FROM channel_messages", one=True)[0]
        n_dms = query_db("SELECT COUNT(*) FROM dms", one=True)[0]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Users", n_users)
        c2.metric("Feed Posts", n_posts)
        c3.metric("Channel Messages", n_channel_msgs)
        c4.metric("Direct Messages", n_dms)

        st.markdown("---")
        st.caption(f"Database size: {os.path.getsize(DB_FILE) / (1024 * 1024):.2f} MB "
                  f"(auto-prunes oldest rows past {MAX_DB_SIZE / (1024 ** 3):.0f} GB)")

        posts_export = query_db("SELECT id, author, text, created_at FROM posts ORDER BY id DESC")
        if posts_export:
            df_posts = pd.DataFrame(posts_export, columns=["ID", "Author", "Text", "Created At"])
            st.download_button("Export All Posts as CSV", df_posts.to_csv(index=False), "posts_export.csv", "text/csv")


# ----------------------------------------------------------------------------
# Notifications
# ----------------------------------------------------------------------------
NOTIF_ICONS = {
    "dm": "✉️", "reply": "↩️", "profile_view": "👁️", "like": "❤️",
    "reaction": "🎭", "follow": "➕",
}
NOTIF_FALLBACK_MSG = {
    "dm": "sent you a direct private message.",
    "reply": "replied directly to one of your messages.",
    "profile_view": "checked out your profile.",
    "like": "liked your post.",
    "reaction": "left a reaction on your message.",
    "follow": "started following you.",
}


def render_notifications():
    st.header("Notification Center")

    if st.button("Mark All as Read"):
        query_db("UPDATE notifications SET is_read = 1 WHERE recipient = ?", (st.session_state.user,), commit=True)
        st.rerun()

    logs = query_db(
        "SELECT id, sender, type, content, ref_type, ref_id, is_read, created_at FROM notifications "
        "WHERE recipient = ? ORDER BY id DESC", (st.session_state.user,))

    if not logs:
        st.info("Your inbox is entirely clear.")
        return

    for n_id, sender, n_type, content, ref_type, ref_id, is_read, created_at in logs:
        status_icon = "🔵" if is_read == 0 else "⚪"
        icon = NOTIF_ICONS.get(n_type, "🔔")
        body = content if content else f"**{sender}** {NOTIF_FALLBACK_MSG.get(n_type, 'sent an update.')}"
        col_msg, col_go = st.columns([5, 1])
        with col_msg:
            st.markdown(f"{status_icon} {icon} {body}")
            st.caption(time_ago(created_at))
        with col_go:
            if ref_type == "post" and st.button("View", key=f"goto_notif_{n_id}"):
                st.session_state.current_view = "Feed"
                st.rerun()
            elif ref_type == "dm" and st.button("View", key=f"goto_notif_{n_id}"):
                st.session_state.current_view = "Direct Messages"
                st.session_state.active_dm_target = sender
                st.rerun()
            elif ref_type == "channel_message" and st.button("View", key=f"goto_notif_{n_id}"):
                st.session_state.current_view = "Servers"
                st.rerun()
            elif n_type in ("profile_view", "follow") and st.button("View", key=f"goto_notif_{n_id}"):
                st.session_state.selected_profile = sender
                st.rerun()
        st.markdown("---")

    query_db("UPDATE notifications SET is_read = 1 WHERE recipient = ?", (st.session_state.user,), commit=True)


# ----------------------------------------------------------------------------
# Main dispatch
# ----------------------------------------------------------------------------
if st.session_state.user is None:
    render_auth_screens()
else:
    render_sidebar()
    view = st.session_state.current_view

    if settings.get("announcement"):
        st.markdown(f"<div class='announcement-banner'>📢 {settings['announcement']}</div>", unsafe_allow_html=True)

    if st.session_state.selected_profile:
        render_profile_card()

    if view == "Feed" and setting_bool(settings, "enable_feed"):
        render_feed()
    elif view == "Servers" and setting_bool(settings, "enable_servers"):
        render_servers()
    elif view == "Direct Messages" and setting_bool(settings, "enable_dms"):
        render_dms()
    elif view == "Profile Settings":
        render_profile_settings()
    elif view == "Admin Dashboard" and is_admin_user:
        render_admin_dashboard()
    elif view == "Notifications":
        render_notifications()
    else:
        st.info("This section is currently disabled by administrators, or unavailable.")