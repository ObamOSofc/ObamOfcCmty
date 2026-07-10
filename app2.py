import os
import sqlite3
import hashlib
import pandas as pd
import streamlit as st
from PIL import Image
from streamlit_cookies_manager import EncryptedCookieManager

# Ensure asset directories exist
os.makedirs("assets/avatars", exist_ok=True)
os.makedirs("assets/uploads", exist_ok=True)

cookies = EncryptedCookieManager(
    prefix="obamofccmty/",
    password=os.environ.get("COOKIES_SECRET_KEY", "a_very_secure_and_long_secret_key_here_123456789")
)
if not cookies.ready():
    st.stop()

DB_FILE = "database.db"
MAX_DB_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB


def cleanup_old_db_data():
    """Prunes old rows if the SQLite database exceeds the 2 GB threshold."""
    if os.path.exists(DB_FILE) and os.path.getsize(DB_FILE) > MAX_DB_SIZE:
        with sqlite3.connect(DB_FILE) as conn:
            c = conn.cursor()
            c.execute("DELETE FROM channel_messages WHERE id IN (SELECT id FROM channel_messages ORDER BY id ASC LIMIT 200)")
            c.execute("DELETE FROM dms WHERE id IN (SELECT id FROM dms ORDER BY id ASC LIMIT 200)")
            c.execute("DELETE FROM posts WHERE id IN (SELECT id FROM posts ORDER BY id ASC LIMIT 50)")
            conn.commit()


def init_db():
    cleanup_old_db_data()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                        username TEXT PRIMARY KEY, password TEXT, bio TEXT, avatar_path TEXT, 
                        role TEXT DEFAULT 'user', last_ip TEXT, last_device TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS follows (
                        follower TEXT, following TEXT, PRIMARY KEY(follower, following))''')
        c.execute('''CREATE TABLE IF NOT EXISTS posts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, author TEXT, text TEXT, file_path TEXT, file_type TEXT, reply_to INTEGER DEFAULT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS likes (
                        post_id INTEGER, username TEXT, PRIMARY KEY(post_id, username))''')
        c.execute('''CREATE TABLE IF NOT EXISTS servers (
                        name TEXT PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS channels (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, server_name TEXT, name TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS channel_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER, user TEXT, text TEXT, reply_to INTEGER DEFAULT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS dms (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, user_from TEXT, user_to TEXT, text TEXT, reply_to INTEGER DEFAULT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS msg_reactions (
                        message_id INTEGER, msg_type TEXT, username TEXT, emoji TEXT, 
                        PRIMARY KEY(message_id, msg_type, username, emoji))''')
        c.execute('''CREATE TABLE IF NOT EXISTS notifications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, 
                        recipient TEXT, 
                        sender TEXT, 
                        type TEXT, 
                        is_read INTEGER DEFAULT 0)''')

        # Migration block to inject columns into your existing database file
        migrations = [
            ("users", "avatar_path TEXT"),
            ("posts", "file_path TEXT"),
            ("posts", "file_type TEXT"),
            ("posts", "reply_to INTEGER DEFAULT NULL"),
            ("channel_messages", "reply_to INTEGER DEFAULT NULL"),
            ("dms", "reply_to INTEGER DEFAULT NULL")
        ]
        for table, column in migrations:
            try:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
            except sqlite3.OperationalError:
                pass  # Already exists, skip error

        admin_hash = hashlib.sha256("Upd20isreal".encode()).hexdigest()
        c.execute("SELECT username FROM users WHERE username = ?", ("ArchPenguin",))
        if not c.fetchone():
            c.execute("INSERT INTO users (username, password, bio, role) VALUES (?, ?, ?, ?)",
                      ("ArchPenguin", admin_hash, "System Administrator", "superuser"))

        c.execute("INSERT OR IGNORE INTO servers (name) VALUES (?)", ("Global Server",))
        c.execute("SELECT id FROM channels WHERE server_name = ? AND name = ?", ("Global Server", "general"))
        if not c.fetchone():
            c.execute("INSERT INTO channels (server_name, name) VALUES (?, ?)", ("Global Server", "general"))
        conn.commit()


init_db()


def query_db(query, args=(), one=False, commit=False):
    cleanup_old_db_data()
    with sqlite3.connect(DB_FILE) as conn:
        c = conn.cursor()
        c.execute(query, args)
        if commit:
            conn.commit()
            rv = c.lastrowid if "INSERT" in query else None
        else:
            rv = c.fetchall()
    return (rv[0] if rv else None) if one else rv


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def get_client_info():
    ctx = st.context
    headers = ctx.headers
    ip = headers.get("X-Forwarded-For", headers.get("Remote-Addr", "127.0.0.1")).split(",")[0].strip()
    user_agent = headers.get("User-Agent", "Unknown Device")
    return ip, user_agent


# Initialize Global Sessions
if "user" not in st.session_state:
    st.session_state.user = cookies.get("auth_user")
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


def save_uploaded_file(uploaded_file):
    if uploaded_file is None:
        return None
    file_ext = uploaded_file.name.split(".")[-1]
    file_hash = hashlib.md5(uploaded_file.getvalue()).hexdigest()
    save_path = f"assets/uploads/{file_hash}.{file_ext}"
    with open(save_path, "wb") as f:
        f.write(uploaded_file.getvalue())
    return save_path


def render_emoji_picker(key_prefix):
    emojis = ["", "😀", "😂", "🔥", "👍", "❤️", "👀", "🚀", "👑", "⚠️"]
    chosen_emoji = st.selectbox("Select an Emoji to Copy", emojis, key=f"picker_{key_prefix}")
    return chosen_emoji if chosen_emoji != "" else None


def render_sidebar(is_admin):
    st.sidebar.title("ObamOfcCmty")
    if os.path.exists("logo.png"):
        st.sidebar.image(Image.open("logo.png"), use_container_width=True)

    st.sidebar.write(f"Logged in as: **{st.session_state.user}**")
    if st.sidebar.button("Log Out"):
        cookies["auth_user"] = ""
        cookies.save()
        st.session_state.user = None
        st.rerun()

    st.sidebar.markdown("---")

    # Calculate unread notifications
    unread = query_db("SELECT COUNT(*) FROM notifications WHERE recipient = ? AND is_read = 0",
                      (st.session_state.user,), one=True)
    unread_count = unread[0] if unread else 0
    badge = f" ({'9+' if unread_count > 9 else unread_count})" if unread_count > 0 else ""

    # Inject glowing styling if there are unread items
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

    views = ["Feed", "Servers", "Direct Messages", f"Notifications{badge}", "Profile Settings"]
    if is_admin:
        views.append("Admin Dashboard")

    for view in views:
        clean_view_name = "Notifications" if "Notifications" in view else view
        if st.sidebar.button(view, use_container_width=True, key=f"sidebar_nav_{clean_view_name}"):
            st.session_state.current_view = clean_view_name
            st.session_state.selected_profile = None
            st.rerun()


user_role_data = query_db("SELECT role FROM users WHERE username = ?", (st.session_state.user,),
                          one=True) if st.session_state.user else None
is_admin_user = user_role_data and user_role_data[0] in ["admin", "superuser"]

if st.session_state.user is None:
    st.title("ObamOfcCmty")
    tab1, tab2 = st.tabs(["Login", "Register"])
    with tab1:
        username_input = st.text_input("Username", key="login_user")
        password_input = st.text_input("Password", type="password", key="login_pass")
        if st.button("Enter"):
            user_data = query_db("SELECT password FROM users WHERE username = ?", (username_input,), one=True)
            if user_data and user_data[0] == hash_password(password_input):
                ip, ua = get_client_info()
                query_db("UPDATE users SET last_ip = ?, last_device = ? WHERE username = ?", (ip, ua, username_input),
                         commit=True)
                cookies["auth_user"] = username_input
                cookies.save()
                st.session_state.user = username_input
                st.rerun()
            else:
                st.error("Invalid credentials.")
    with tab2:
        reg_user = st.text_input("Choose Username", key="reg_user")
        reg_pass = st.text_input("Choose Password", type="password", key="reg_pass")
        if st.button("Create Account"):
            if not reg_user.strip() or not reg_pass.strip():
                st.error("Fields cannot be empty.")
            elif query_db("SELECT username FROM users WHERE username = ?", (reg_user,), one=True):
                st.error("Username taken.")
            else:
                ip, ua = get_client_info()
                query_db("INSERT INTO users (username, password, bio, last_ip, last_device) VALUES (?, ?, ?, ?, ?)",
                         (reg_user, hash_password(reg_pass), "", ip, ua), commit=True)
                st.success("Account created. Log in now.")
else:
    render_sidebar(is_admin_user)
    view = st.session_state.current_view

    # Profile Quick Modal Overlay View
    if st.session_state.selected_profile:
        st.markdown(f"## Profile: {st.session_state.selected_profile}")
        p_info = query_db("SELECT bio, avatar_path, role FROM users WHERE username = ?",
                          (st.session_state.selected_profile,), one=True)
        if st.session_state.user and st.session_state.selected_profile != st.session_state.user:
            query_db("INSERT INTO notifications (recipient, sender, type) VALUES (?, ?, 'profile_view')",
                     (st.session_state.selected_profile, st.session_state.user), commit=True)
        if p_info:
            if p_info[1] and os.path.exists(p_info[1]):
                st.image(p_info[1], width=120)
            st.write(f"**Role:** {p_info[2].upper()}")
            st.write(f"**Bio:** {p_info[0] if p_info[0] else '*No bio written yet.*'}")
        if st.button("Close Profile View"):
            st.session_state.selected_profile = None
            st.rerun()
        st.markdown("---")

    if view == "Feed":
        st.header("Feed Portal")
        mode = st.radio("Display Layout Mode", ["Standard Stream", "TikTok Scroll Mode"], horizontal=True)
        with st.form("new_post", clear_on_submit=True):
            post_text = st.text_area("What is happening?")
            uploaded_file = st.file_uploader("Upload Image or Video Media",
                                             type=["mp4", "mov", "avi", "png", "jpg", "jpeg"])

            emoji_picked = render_emoji_picker("feed_post")
            if emoji_picked:
                st.info(f"Selected: {emoji_picked} (You can copy-paste this into your post text box)")

            if st.form_submit_button("Publish Post"):
                if post_text.strip() or uploaded_file:
                    f_path = save_uploaded_file(uploaded_file)
                    f_type = "image" if uploaded_file and "image" in uploaded_file.type else "video" if uploaded_file else None
                    query_db("INSERT INTO posts (author, text, file_path, file_type) VALUES (?, ?, ?, ?)",
                             (st.session_state.user, post_text, f_path, f_type), commit=True)
                    st.rerun()
        posts = query_db("SELECT id, author, text, file_path, file_type FROM posts ORDER BY id DESC")

        if mode == "TikTok Scroll Mode" and posts:
            if "tiktok_idx" not in st.session_state:
                st.session_state.tiktok_idx = 0
            st.session_state.tiktok_idx = min(max(0, st.session_state.tiktok_idx), len(posts) - 1)

            p_id, author, text, file_path, file_type = posts[st.session_state.tiktok_idx]
            st.markdown(f"### Post {st.session_state.tiktok_idx + 1} of {len(posts)}")

            if st.button(f"👤 View {author}'s Full Profile", key=f"view_prof_tt_{p_id}"):
                st.session_state.selected_profile = author
                st.rerun()

            if text:
                st.write(text)
            if file_path and os.path.exists(file_path):
                if file_type == "image":
                    st.image(file_path, use_container_width=True)
                else:
                    st.video(file_path)

            c1, c2 = st.columns(2)
            if c1.button("◀ Previous", use_container_width=True) and st.session_state.tiktok_idx > 0:
                st.session_state.tiktok_idx -= 1
                st.rerun()
            if c2.button("Next ▶", use_container_width=True) and st.session_state.tiktok_idx < len(posts) - 1:
                st.session_state.tiktok_idx += 1
                st.rerun()

        else:
            for p_id, author, text, file_path, file_type in posts:
                col_author, col_view_p = st.columns([3, 1])
                with col_author:
                    st.markdown(f"**{author}**")
                with col_view_p:
                    if st.button("View Profile", key=f"vp_{p_id}"):
                        st.session_state.selected_profile = author
                        st.rerun()

                if text:
                    st.write(text)
                if file_path and os.path.exists(file_path):
                    if file_type == "image":
                        st.image(file_path, width=400)
                    else:
                        st.video(file_path)

                likes = query_db("SELECT username FROM likes WHERE post_id = ?", (p_id,))
                is_liked = any(l[0] == st.session_state.user for l in likes)
                like_label = f"Liked ({len(likes)})" if is_liked else f"Like ({len(likes)})"

                col_lk, col_del = st.columns([1, 8])
                with col_lk:
                    if st.button(like_label, key=f"like_{p_id}"):
                        if is_liked:
                            query_db("DELETE FROM likes WHERE post_id = ? AND username = ?",
                                     (p_id, st.session_state.user), commit=True)
                        else:
                            query_db("INSERT INTO likes (post_id, username) VALUES (?, ?)",
                                     (p_id, st.session_state.user), commit=True)
                            # Notify author
                            if author != st.session_state.user:
                                query_db("INSERT INTO notifications (recipient, sender, type) VALUES (?, ?, 'like')",
                                         (author, st.session_state.user), commit=True)
                        st.rerun()
                with col_del:
                    if is_admin_user:
                        if st.button("Delete Post", key=f"del_post_{p_id}"):
                            query_db("DELETE FROM posts WHERE id = ?", (p_id,), commit=True)
                            query_db("DELETE FROM likes WHERE post_id = ?", (p_id,), commit=True)
                            st.rerun()
                st.markdown("---")

    elif view == "Servers":
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
                        if st.button("Cancel Reply"):
                            st.session_state.reply_target_id = None
                            st.rerun()


                    @st.fragment(run_every=2)
                    def show_server_chat(channel_idx):
                        messages = query_db(
                            "SELECT id, user, text, reply_to FROM channel_messages WHERE channel_id = ? ORDER BY id ASC",
                            (channel_idx,))
                        for msg_id, msg_user, msg_text, reply_to in messages:
                            reactions = query_db(
                                "SELECT emoji, COUNT(*) FROM msg_reactions WHERE message_id = ? AND msg_type = 'channel' GROUP BY emoji",
                                (msg_id,))
                            react_str = " ".join([f"{r[0]}{r[1]}" for r in reactions])

                            if reply_to:
                                parent_msg = query_db("SELECT user, text FROM channel_messages WHERE id = ?",
                                                      (reply_to,), one=True)
                                if parent_msg:
                                    st.caption(f"↳ Replying to @{parent_msg[0]}: *{parent_msg[1][:30]}...*")

                            col_msg, col_act = st.columns([3, 2])
                            with col_msg:
                                if st.button(f"👤 {msg_user}", key=f"user_profile_link_{msg_id}"):
                                    st.session_state.selected_profile = msg_user
                                    st.rerun()
                                st.markdown(f"{msg_text}  \n*{react_str}*")
                            with col_act:
                                b_rep, b_reac, b_del = st.columns(3)
                                if b_rep.button("⮪", key=f"rep_ch_{msg_id}", help="Reply"):
                                    st.session_state.reply_target_id = msg_id
                                    st.rerun()
                                if b_reac.button("👍", key=f"react_ch_{msg_id}"):
                                    query_db(
                                        "INSERT OR IGNORE INTO msg_reactions (message_id, msg_type, username, emoji) VALUES (?, 'channel', ?, '👍')",
                                        (msg_id, st.session_state.user), commit=True)
                                    if msg_user != st.session_state.user:
                                        query_db(
                                            "INSERT INTO notifications (recipient, sender, type) VALUES (?, ?, 'reaction')",
                                            (msg_user, st.session_state.user), commit=True)
                                if is_admin_user and b_del.button("🗑️", key=f"del_ch_{msg_id}"):
                                    query_db("DELETE FROM channel_messages WHERE id = ?", (msg_id,), commit=True)
                                    st.rerun()


                    show_server_chat(ch_id)

                    with st.form("send_msg", clear_on_submit=True):
                        msg_text = st.text_input("Write Message")
                        if st.form_submit_button("Send"):
                            if msg_text.strip():
                                query_db(
                                    "INSERT INTO channel_messages (channel_id, user, text, reply_to) VALUES (?, ?, ?, ?)",
                                    (ch_id, st.session_state.user, msg_text, st.session_state.reply_target_id),
                                    commit=True)
                                if st.session_state.reply_target_id:
                                    parent_user = query_db("SELECT user FROM channel_messages WHERE id = ?", (st.session_state.reply_target_id,), one=True)
                                    if parent_user and parent_user[0] != st.session_state.user:
                                        query_db("INSERT INTO notifications (recipient, sender, type) VALUES (?, ?, 'reply')", (parent_user[0], st.session_state.user), commit=True)
                                st.session_state.reply_target_id = None
                                st.rerun()

    elif view == "Direct Messages":
        st.header("Direct Messaging Vault")

        active_dm_nodes = query_db("""SELECT DISTINCT user_to FROM dms WHERE user_from = ? 
                                      UNION 
                                      SELECT DISTINCT user_from FROM dms WHERE user_to = ?""",
                                   (st.session_state.user, st.session_state.user))
        dm_list = [node[0] for node in active_dm_nodes if node[0] != st.session_state.user]

        col_dm_nav, col_dm_chat = st.columns([1, 2])

        with col_dm_nav:
            st.subheader("Conversations")
            for person in dm_list:
                if st.button(f"💬 {person}", key=f"dm_target_{person}", use_container_width=True):
                    st.session_state.active_dm_target = person
                    st.rerun()

            st.markdown("---")
            search_new_dm = st.text_input("Start New DM (Type Username)")
            if st.button("Open Inbox"):
                if search_new_dm.strip() and query_db("SELECT username FROM users WHERE username = ?",
                                                      (search_new_dm.strip(),), one=True):
                    st.session_state.active_dm_target = search_new_dm.strip()
                    st.rerun()
                else:
                    st.error("User does not exist.")

        with col_dm_chat:
            target_user = st.session_state.active_dm_target
            if target_user:
                st.subheader(f"Chat Room: @{target_user}")


                @st.fragment(run_every=2)
                def show_dm_chat(target):
                    messages = query_db('''SELECT id, user_from, text FROM dms 
                                           WHERE (user_from = ? AND user_to = ?) OR (user_from = ? AND user_to = ?) 
                                           ORDER BY id ASC''',
                                        (st.session_state.user, target, target, st.session_state.user))
                    for msg_id, msg_from, msg_text in messages:
                        st.markdown(f"**{msg_from}**: {msg_text}")


                show_dm_chat(target_user)

                with st.form("dm_form", clear_on_submit=True):
                    dm_text = st.text_input("Send Private Message")
                    if st.form_submit_button("Send DM"):
                        if dm_text.strip():
                            query_db("INSERT INTO dms (user_from, user_to, text) VALUES (?, ?, ?)",
                                     (st.session_state.user, target_user, dm_text), commit=True)
                            query_db("INSERT INTO notifications (recipient, sender, type) VALUES (?, ?, 'dm')",
                                     (target_user, st.session_state.user), commit=True)
                            st.rerun()
            else:
                st.info(
                    "Select a contact from the active conversations tracker or type a username to begin a dialogue.")

    elif view == "Profile Settings":
        st.header("Profile Configurations")
        u_data = query_db("SELECT bio, avatar_path FROM users WHERE username = ?", (st.session_state.user,), one=True)

        new_bio = st.text_area("Update Bio Information", value=u_data[0] if u_data else "")
        avatar_file = st.file_uploader("Upload New Profile Picture", type=["png", "jpg", "jpeg"])

        if st.button("Commit Profile Changes"):
            av_path = save_uploaded_file(avatar_file) if avatar_file else (u_data[1] if u_data else None)
            query_db("UPDATE users SET bio = ?, avatar_path = ? WHERE username = ?",
                     (new_bio, av_path, st.session_state.user), commit=True)
            st.success("Successfully written configurations to persistent profile parameters.")
            st.rerun()

    elif view == "Admin Dashboard" and is_admin_user:
        st.header("Admin Operations Control center")
        cmd_user = st.text_input("Target User Profile")
        cmd_action = st.selectbox("Action", ["Promote to Admin", "Demote to User", "Delete Profile Data Entirely"])

        if st.button("Execute Action"):
            target_role = query_db("SELECT role FROM users WHERE username = ?", (cmd_user,), one=True)
            if not target_role:
                st.error("Target individual does not exist.")
            elif cmd_user == "ArchPenguin":
                st.error("Superuser credentials cannot be mutated.")
            else:
                if cmd_action == "Promote to Admin":
                    query_db("UPDATE users SET role = 'admin' WHERE username = ?", (cmd_user,), commit=True)
                elif cmd_action == "Demote to User":
                    query_db("UPDATE users SET role = 'user' WHERE username = ?", (cmd_user,), commit=True)
                elif cmd_action == "Delete Profile Data Entirely":
                    query_db("DELETE FROM users WHERE username = ?", (cmd_user,), commit=True)
                st.success("Administrative operation completed successfully.")
                st.rerun()

    elif view == "Notifications":
        st.header("Notification Center")

        if st.button("Mark All as Read"):
            query_db("UPDATE notifications SET is_read = 1 WHERE recipient = ?", (st.session_state.user,), commit=True)
            st.rerun()

        logs = query_db("SELECT id, sender, type, is_read FROM notifications WHERE recipient = ? ORDER BY id DESC",
                        (st.session_state.user,))

        if not logs:
            st.info("Your inbox is entirely clear.")
        else:
            for n_id, sender, n_type, is_read in logs:
                status_icon = "🔵" if is_read == 0 else "⚪"

                if n_type == "dm":
                    msg = f"{status_icon} **{sender}** sent you a direct private message."
                elif n_type == "reply":
                    msg = f"{status_icon} **{sender}** replied directly to one of your messages."
                elif n_type == "profile_view":
                    msg = f"{status_icon} **{sender}** checked out your profile layout parameters."
                elif n_type == "like":
                    msg = f"{status_icon} **{sender}** liked your feed transmission stream."
                elif n_type == "reaction":
                    msg = f"{status_icon} **{sender}** left a structural reaction on your text chunk."
                else:
                    msg = f"{status_icon} Activity update recorded from **{sender}**."

                st.markdown(msg)