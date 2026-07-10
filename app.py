import os
import sqlite3
import hashlib
import streamlit as st
from PIL import Image

st.set_page_config(page_title="ObamOfcCmty", layout="wide")

DB_FILE = "database.db"


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY, password TEXT, bio TEXT, avatar BLOB)''')
    c.execute('''CREATE TABLE IF NOT EXISTS follows (
                    follower TEXT, following TEXT, PRIMARY KEY(follower, following))''')
    c.execute('''CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, author TEXT, text TEXT, video BLOB)''')
    c.execute('''CREATE TABLE IF NOT EXISTS likes (
                    post_id INTEGER, username TEXT, PRIMARY KEY(post_id, username))''')
    c.execute('''CREATE TABLE IF NOT EXISTS servers (
                    name TEXT PRIMARY KEY)''')
    c.execute('''CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, server_name TEXT, name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS channel_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER, user TEXT, text TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS dms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_from TEXT, user_to TEXT, text TEXT)''')

    admin_hash = hashlib.sha256("Upd20isreal".encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO users (username, password, bio) VALUES (?, ?, ?)",
              ("ArchPenguin", admin_hash, "System Administrator"))
    c.execute("INSERT OR IGNORE INTO servers (name) VALUES (?)", ("Global Server",))
    c.execute("SELECT id FROM channels WHERE server_name = ? AND name = ?", ("Global Server", "general"))
    if not c.fetchone():
        c.execute("INSERT INTO channels (server_name, name) VALUES (?, ?)", ("Global Server", "general"))
    conn.commit()
    conn.close()


init_db()


def query_db(query, args=(), one=False, commit=False):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(query, args)
    if commit:
        conn.commit()
        rv = c.lastrowid if "INSERT" in query else None
    else:
        rv = c.fetchall()
    conn.close()
    return (rv[0] if rv else None) if one else rv


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


if "user" not in st.session_state:
    st.session_state.user = None
if "current_view" not in st.session_state:
    st.session_state.current_view = "Feed"
if "active_server" not in st.session_state:
    st.session_state.active_server = "Global Server"
if "active_channel_id" not in st.session_state:
    ch = query_db("SELECT id FROM channels WHERE server_name = ? AND name = ?", ("Global Server", "general"), one=True)
    st.session_state.active_channel_id = ch[0] if ch else None


def render_sidebar():
    st.sidebar.title("ObamOfcCmty")
    if os.path.exists("logo.png"):
        st.sidebar.image(Image.open("logo.png"), use_container_width=True)

    st.sidebar.write(f"Logged in as: **{st.session_state.user}**")
    if st.sidebar.button("Log Out"):
        st.session_state.user = None
        st.rerun()

    st.sidebar.markdown("---")

    views = ["Feed", "Servers", "Direct Messages", "Profile Settings"]
    for view in views:
        if st.sidebar.button(view, use_container_width=True):
            st.session_state.current_view = view
            st.rerun()


if st.session_state.user is None:
    st.title("ObamOfcCmty")
    if os.path.exists("logo.png"):
        st.image(Image.open("logo.png"), width=150)

    tab1, tab2 = st.tabs(["Login", "Register"])

    with tab1:
        username_input = st.text_input("Username", key="login_user")
        password_input = st.text_input("Password", type="password", key="login_pass")
        if st.button("Enter"):
            user_data = query_db("SELECT password FROM users WHERE username = ?", (username_input,), one=True)
            if user_data and user_data[0] == hash_password(password_input):
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
                query_db("INSERT INTO users (username, password, bio) VALUES (?, ?, ?)",
                         (reg_user, hash_password(reg_pass), ""), commit=True)
                st.success("Account created. You can now log in.")
else:
    render_sidebar()
    view = st.session_state.current_view

    if view == "Feed":
        st.header("Feed")

        with st.form("new_post", clear_on_submit=True):
            post_text = st.text_area("What is happening?")
            uploaded_video = st.file_uploader("Upload Video", type=["mp4", "mov", "avi"])
            if st.form_submit_button("Post"):
                if post_text.strip() or uploaded_video:
                    video_data = uploaded_video.read() if uploaded_video else None
                    query_db("INSERT INTO posts (author, text, video) VALUES (?, ?, ?)",
                             (st.session_state.user, post_text, video_data), commit=True)
                    st.rerun()

        posts = query_db("SELECT id, author, text, video FROM posts ORDER BY id DESC")
        for p_id, author, text, video in posts:
            st.markdown(f"### {author}")
            if text:
                st.write(text)
            if video:
                st.video(video)

            likes = query_db("SELECT username FROM likes WHERE post_id = ?", (p_id,))
            likes_count = len(likes)
            is_liked = any(l[0] == st.session_state.user for l in likes)
            like_label = f"Liked ({likes_count})" if is_liked else f"Like ({likes_count})"

            if st.button(like_label, key=f"like_{p_id}"):
                if is_liked:
                    query_db("DELETE FROM likes WHERE post_id = ? AND username = ?", (p_id, st.session_state.user),
                             commit=True)
                else:
                    query_db("INSERT INTO likes (post_id, username) VALUES (?, ?)", (p_id, st.session_state.user),
                             commit=True)
                st.rerun()
            st.markdown("---")

    elif view == "Servers":
        st.header("Servers")
        col1, col2 = st.columns([1, 3])

        with col1:
            st.subheader("Navigation")
            new_server = st.text_input("New Server Name")
            if st.button("Create Server"):
                if new_server.strip() and not query_db("SELECT name FROM servers WHERE name = ?", (new_server,),
                                                       one=True):
                    query_db("INSERT INTO servers (name) VALUES (?)", (new_server,), commit=True)
                    query_db("INSERT INTO channels (server_name, name) VALUES (?, ?)", (new_server, "general"),
                             commit=True)
                    st.rerun()

            st.markdown("---")
            servers = query_db("SELECT name FROM servers")
            for server in servers:
                if st.button(server[0], key=f"srv_{server[0]}", use_container_width=True):
                    st.session_state.active_server = server[0]
                    first_ch = query_db("SELECT id FROM channels WHERE server_name = ? LIMIT 1", (server[0],), one=True)
                    st.session_state.active_channel_id = first_ch[0] if first_ch else None
                    st.rerun()

        with col2:
            srv = st.session_state.active_server
            st.subheader(f"Server: {srv}")

            ch_col, chat_col = st.columns([1, 2])
            with ch_col:
                st.write("**Channels**")
                new_ch = st.text_input("New Channel")
                if st.button("Add Channel"):
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

                    messages = query_db("SELECT user, text FROM channel_messages WHERE channel_id = ? ORDER BY id ASC",
                                        (ch_id,))
                    for msg_user, msg_text in messages:
                        st.markdown(f"**{msg_user}**: {msg_text}")

                    with st.form("send_msg", clear_on_submit=True):
                        msg_text = st.text_input("Message")
                        if st.form_submit_button("Send"):
                            if msg_text.strip():
                                query_db("INSERT INTO channel_messages (channel_id, user, text) VALUES (?, ?, ?)",
                                         (ch_id, st.session_state.user, msg_text), commit=True)
                                st.rerun()

    elif view == "Direct Messages":
        st.header("Direct Messages")
        target_user = st.text_input("Enter Username to Chat")
        if query_db("SELECT username FROM users WHERE username = ?", (target_user,),
                    one=True) and target_user != st.session_state.user:
            messages = query_db('''SELECT user_from, text FROM dms 
                                   WHERE (user_from = ? AND user_to = ?) OR (user_from = ? AND user_to = ?) 
                                   ORDER BY id ASC''',
                                (st.session_state.user, target_user, target_user, st.session_state.user))
            for msg_from, msg_text in messages:
                st.markdown(f"**{msg_from}**: {msg_text}")

            with st.form("dm_form", clear_on_submit=True):
                dm_text = st.text_input("Message")
                if st.form_submit_button("Send"):
                    if dm_text.strip():
                        query_db("INSERT INTO dms (user_from, user_to, text) VALUES (?, ?, ?)",
                                 (st.session_state.user, target_user, dm_text), commit=True)
                        st.rerun()
        elif target_user:
            st.error("User not found.")

    elif view == "Profile Settings":
        st.header("Profile Settings")
        u_data = query_db("SELECT bio FROM users WHERE username = ?", (st.session_state.user,), one=True)
        followers = query_db("SELECT follower FROM follows WHERE following = ?", (st.session_state.user,))
        following = query_db("SELECT following FROM follows WHERE follower = ?", (st.session_state.user,))

        st.write(f"Followers: {len(followers)} | Following: {len(following)}")

        new_bio = st.text_area("Bio", value=u_data[0] if u_data else "")
        avatar_file = st.file_uploader("Upload Profile Picture", type=["png", "jpg", "jpeg"])

        if st.button("Save Profile"):
            avatar_data = avatar_file.read() if avatar_file else None
            if avatar_data:
                query_db("UPDATE users SET bio = ?, avatar = ? WHERE username = ?",
                         (new_bio, avatar_data, st.session_state.user), commit=True)
            else:
                query_db("UPDATE users SET bio = ? WHERE username = ?", (new_bio, st.session_state.user), commit=True)
            st.success("Profile updated.")
            st.rerun()

        st.markdown("---")
        st.subheader("Find Users")
        search_u = st.text_input("Search Username")
        if query_db("SELECT username FROM users WHERE username = ?", (search_u,),
                    one=True) and search_u != st.session_state.user:
            target_bio = query_db("SELECT bio FROM users WHERE username = ?", (search_u,), one=True)[0]
            st.write(f"**{search_u}**")
            st.write(target_bio)

            is_following = query_db("SELECT 1 FROM follows WHERE follower = ? AND following = ?",
                                    (st.session_state.user, search_u), one=True)
            if is_following:
                if st.button("Unfollow"):
                    query_db("DELETE FROM follows WHERE follower = ? AND following = ?",
                             (st.session_state.user, search_u), commit=True)
                    st.rerun()
            else:
                if st.button("Follow"):
                    query_db("INSERT INTO follows (follower, following) VALUES (?, ?)",
                             (st.session_state.user, search_u), commit=True)
                    st.rerun()