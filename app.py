# app.py
import os
import streamlit as st
import pandas as pd
from db_manager import execute_query, hash_password, get_dm_partners, supabase

# 1. Page Configuration & Custom CSS Injection
st.set_page_config(page_title="ObamOfcCmty Premium", layout="wide", initial_sidebar_state="expanded")

# Smooth custom styles matching professional night dark-modes
st.markdown("""
<style>
    .stApp { background-color: #0e1117; color: #c9d1d9; }
    div[data-testid="stExpander"] { background-color: #161b22; border-radius: 8px; }
    .dm-bubble-me { background-color: #238636; padding: 10px; border-radius: 12px 12px 0px 12px; margin: 5px 0; text-align: right; }
    .dm-bubble-them { background-color: #21262d; padding: 10px; border-radius: 12px 12px 12px 0px; margin: 5px 0; text-align: left; }
</style>
""", unsafe_with_html=True)

# 2. Session Context Init
if "user" not in st.session_state:
    st.session_state.user = None
if "current_view" not in st.session_state:
    st.session_state.current_view = "Feed"
if "active_server" not in st.session_state:
    st.session_state.active_server = "Global Server"
if "active_channel_id" not in st.session_state:
    st.session_state.active_channel_id = None


# Helper Client Analytics info
def get_client_info():
    ctx = st.context
    headers = ctx.headers
    ip = headers.get("X-Forwarded-For", headers.get("Remote-Addr", "127.0.0.1")).split(",")[0].strip()
    ua = headers.get("User-Agent", "Desktop Browser")
    return ip, ua


# 3. Security Routing Gateway (Login/Register)
if st.session_state.user is None:
    st.title("🚀 ObamOfcCmty Engine")
    tab1, tab2 = st.tabs(["🔒 Secure Login", "📝 Open Account"])

    with tab1:
        username_input = st.text_input("Username", key="l_user")
        password_input = st.text_input("Password", type="password", key="l_pass")
        if st.button("Enter Platform", use_container_width=True):
            user_data = execute_query("users", "select", filters={"username": username_input})
            if user_data and user_data[0]['password'] == hash_password(password_input):
                ip, ua = get_client_info()
                execute_query("users", "update", data={"last_ip": ip, "last_device": ua},
                              filters={"username": username_input})
                st.session_state.user = username_input
                st.rerun()
            else:
                st.error("Access Refused: Invalid Credentials.")

    with tab2:
        reg_user = st.text_input("Preferred Username", key="r_user")
        reg_pass = st.text_input("Secure Password", type="password", key="r_pass")
        if st.button("Register Credentials", use_container_width=True):
            if reg_user.strip() and reg_pass.strip():
                existing = execute_query("users", "select", filters={"username": reg_user})
                if existing:
                    st.error("Identifier occupied.")
                else:
                    ip, ua = get_client_info()
                    execute_query("users", "insert", data={
                        "username": reg_user, "password": hash_password(reg_pass),
                        "bio": "New Community Node", "role": "user", "last_ip": ip, "last_device": ua
                    })
                    st.success("Registration complete! Switch to Login tab.")
    st.stop()

# 4. User Role Verification Layer
user_info = execute_query("users", "select", filters={"username": st.session_state.user})
is_admin = user_info and user_info[0].get("role") in ["admin", "superuser"]

# 5. Global Sidebar Controls
st.sidebar.title("ObamOfcCmty")
st.sidebar.subheader(f"🌐 @{st.session_state.user}")
if st.sidebar.button("🔌 Sign Out", use_container_width=True):
    st.session_state.user = None
    st.rerun()

st.sidebar.markdown("---")
views = ["Feed", "Servers Hub (Discord Mode)", "Direct Messages", "Accounts Directory", "Profile Settings"]
if is_admin:
    views.append("Admin Dashboard")

for v in views:
    if st.sidebar.button(v, use_container_width=True,
                         variant="secondary" if st.session_state.current_view != v else "primary"):
        st.session_state.current_view = v
        st.rerun()

view = st.session_state.current_view

# ================== VIEW 1: REDDIT-STYLE FEED ==================
if view == "Feed":
    st.header("📌 Global Community Feed")

    with st.form("new_reddit_post", clear_on_submit=True):
        p_text = st.text_area("Share something interesting...", placeholder="What's happening around you?")
        p_media = st.text_input("Image/Video URL attachment (Optional)")
        if st.form_submit_button("Broadcast Post"):
            if p_text.strip() or p_media.strip():
                execute_query("posts", "insert",
                              data={"author": st.session_state.user, "text": p_text, "media_url": p_media})
                st.rerun()

    posts = execute_query("posts", "select", order_by="id", desc=True)
    for p in posts:
        with st.container(border=True):
            st.markdown(f"**🟢 @{p['author']}** posted:")
            if p['text']: st.write(p['text'])
            if p.get('media_url'):
                if any(ext in p['media_url'].lower() for ext in ['.mp4', '.mov', '.avi']):
                    st.video(p['media_url'])
                else:
                    st.image(p['media_url'], use_container_width=True)

            # Engagement Metrics Array
            likes = execute_query("likes", "select", filters={"post_id": p['id']})
            likes_count = len(likes)
            has_liked = any(lk['username'] == st.session_state.user for lk in likes)

            col_lk, col_del = st.columns([1, 5])
            if col_lk.button(f"❤️ ({likes_count})" if has_liked else f"🤍 ({likes_count})", key=f"lk_{p['id']}"):
                if has_liked:
                    execute_query("likes", "delete", filters={"post_id": p['id'], "username": st.session_state.user})
                else:
                    execute_query("likes", "insert", data={"post_id": p['id'], "username": st.session_state.user})
                st.rerun()

            if is_admin and col_del.button("🗑️ Purge", key=f"del_{p['id']}"):
                execute_query("posts", "delete", filters={"id": p['id']})
                st.rerun()

# ================== VIEW 2: DISCORD-STYLE SERVERS ==================
elif view == "Servers Hub (Discord Mode)":
    st.header("💬 Connected Communities")
    srv_col, ch_col, chat_col = st.columns([1, 1, 2])

    with srv_col:
        st.subheader("Guilds")
        srv_name = st.text_input("New Server")
        if st.button("➕ Add", use_container_width=True) and srv_name.strip():
            execute_query("servers", "insert", data={"name": srv_name})
            execute_query("channels", "insert", data={"server_name": srv_name, "name": "general"})
            st.rerun()

        all_srvs = execute_query("servers", "select")
        for s in all_srvs:
            if st.button(f"📁 {s['name']}", key=f"s_{s['name']}", use_container_width=True):
                st.session_state.active_server = s['name']
                st.rerun()

    current_srv = st.session_state.active_server

    with ch_col:
        st.subheader(f"# {current_srv}")
        new_ch = st.text_input("New Channel")
        if st.button("➕ Create Channel", use_container_width=True) and new_ch.strip():
            execute_query("channels", "insert", data={"server_name": current_srv, "name": new_ch})
            st.rerun()

        channels = execute_query("channels", "select", filters={"server_name": current_srv})
        if channels and not st.session_state.active_channel_id:
            st.session_state.active_channel_id = channels[0]['id']

        for ch in channels:
            if st.button(f"💬 {ch['name']}", key=f"ch_{ch['id']}", use_container_width=True):
                st.session_state.active_channel_id = ch['id']
                st.rerun()

    with chat_col:
        st.subheader("Channel Communication Stream")
        active_ch = st.session_state.active_channel_id
        if active_ch:
            # Fixed-height scrollable window to prevent scrolling decay
            with st.container(height=400, border=True):
                msgs = execute_query("channel_messages", "select", filters={"channel_id": active_ch}, order_by="id")
                for m in msgs:
                    st.markdown(f"**@{m['user']}**: {m['text']}")

            with st.form("send_ch_msg", clear_on_submit=True):
                txt = st.text_input("Type a message...", label_visibility="collapsed")
                if st.form_submit_button("Send") and txt.strip():
                    execute_query("channel_messages", "insert",
                                  data={"channel_id": active_ch, "user": st.session_state.user, "text": txt})
                    st.rerun()

# ================== VIEW 3: SMART DM MATRIX ==================
elif view == "Direct Messages":
    st.header("📥 Direct Message Matrices")
    list_col, main_chat_col = st.columns([1, 2])

    with list_col:
        st.subheader("Recent Contacts")
        active_partners = get_dm_partners(st.session_state.user)
        target_search = st.text_input("🔍 Start conversation (Enter Username)")

        selected_partner = None
        if target_search.strip():
            selected_partner = target_search.strip()
        elif active_partners:
            selected_partner = st.radio("Active Threads", active_partners)

    with main_chat_col:
        if selected_partner:
            st.subheader(f"Conversation with @{selected_partner}")

            with st.container(height=450, border=True):
                # Bidirectional message resolution query logic
                raw_dms = execute_query("dms", "select", order_by="id")
                filtered_dms = [d for d in raw_dms if
                                (d['user_from'] == st.session_state.user and d['user_to'] == selected_partner) or (
                                            d['user_from'] == selected_partner and d[
                                        'user_to'] == st.session_state.user)]

                for dm in filtered_dms:
                    style_class = "dm-bubble-me" if dm['user_from'] == st.session_state.user else "dm-bubble-them"
                    st.markdown(f"<div class='{style_class}'><b>@{dm['user_from']}:</b> {dm['text']}</div>",
                                unsafe_with_html=True)
                    if dm.get("media_url"):
                        st.image(dm["media_url"], width=250)

            with st.form("dm_input_form", clear_on_submit=True):
                d_msg = st.text_input("Secure message body")
                d_media = st.text_input("Image Attachment URL (Optional)")
                if st.form_submit_button("Transmit DM") and d_msg.strip():
                    execute_query("dms", "insert",
                                  data={"user_from": st.session_state.user, "user_to": selected_partner, "text": d_msg,
                                        "media_url": d_media})
                    st.rerun()
        else:
            st.info("Pick or search an entity handle to prompt messaging infrastructure.")

# ================== VIEW 4: TWITTER/X LOOKS ACCOUNT DIRECTORY ==================
elif view == "Accounts Directory":
    st.header("🗂️ Global Account Nodes")
    all_users_list = [u['username'] for u in execute_query("users", "select") if u['username'] != st.session_state.user]
    chosen_lookup = st.selectbox("Search Identity Profiles", [""] + all_users_list)

    if chosen_lookup:
        tgt_data = execute_query("users", "select", filters={"username": chosen_lookup})[0]
        with st.container(border=True):
            st.subheader(f"✨ Profile: @{tgt_data['username']}")
            st.markdown(f"**Bio:** *{tgt_data.get('bio', 'No description configured.')}*")
            st.caption(f"Network Authorization Class: {tgt_data.get('role', 'user').upper()}")

            # Follow system calculations
            is_following = execute_query("follows", "select",
                                         filters={"follower": st.session_state.user, "following": chosen_lookup})
            if is_following:
                if st.button("Unfollow Target Account", type="primary"):
                    execute_query("follows", "delete",
                                  filters={"follower": st.session_state.user, "following": chosen_lookup})
                    st.rerun()
            else:
                if st.button("Follow Target Account"):
                    execute_query("follows", "insert",
                                  data={"follower": st.session_state.user, "following": chosen_lookup})
                    st.rerun()

# ================== VIEW 5: PROFILE SETTINGS ==================
elif view == "Profile Settings":
    st.header("⚙️ Personal System Preferences")
    current_bio = user_info[0].get("bio", "")
    new_bio = st.text_area("Modify Account Biography", value=current_bio)
    if st.button("Commit Configuration Updates"):
        execute_query("users", "update", data={"bio": new_bio}, filters={"username": st.session_state.user})
        st.success("Changes permanently pushed to cloud context stores.")
        st.rerun()

# ================== VIEW 6: ADMIN CONTROL PANEL ==================
elif view == "Admin Dashboard" and is_admin:
    st.header("🛡️ System Administration Console")

    t_user = st.text_input("Target Account Identifier")
    t_action = st.selectbox("Action Execution Sequence",
                            ["Promote to Admin", "Demote to User", "Purge Data Store Profile"])

    if st.button("Run Administrative Action"):
        exists = execute_query("users", "select", filters={"username": t_user})
        if not exists:
            st.error("Target node missing.")
        elif t_user == "ArchPenguin":
            st.error("Immutable system core context cannot be changed.")
        else:
            if t_action == "Promote to Admin":
                execute_query("users", "update", data={"role": "admin"}, filters={"username": t_user})
            elif t_action == "Demote to User":
                execute_query("users", "update", data={"role": "user"}, filters={"username": t_user})
            elif t_action == "Purge Data Store Profile":
                execute_query("users", "delete", filters={"username": t_user})
            st.success("Administrative operation completed successfully.")
            st.rerun()

    st.markdown("---")
    st.subheader("Global Security Audit Log")
    records = execute_query("users", "select")
    st.dataframe(pd.DataFrame(records)[["username", "role", "last_ip", "last_device"]], use_container_width=True)