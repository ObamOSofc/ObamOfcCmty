# db_manager.py
import os
import hashlib
from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://supabase.com/dashboard/project/tirjeabivhdqnowwhjrm")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "https://tirjeabivhdqnowwhjrm.supabase.co/rest/v1/")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def execute_query(table: str, action: str, data: dict = None, filters: dict = None, order_by: str = None, desc: bool = False):
    try:
        query = supabase.table(table)
        if action == "insert":
            return query.insert(data).execute()
        elif action == "update":
            q = query.update(data)
            for k, v in filters.items():
                q = q.eq(k, v)
            return q.execute()
        elif action == "delete":
            q = query.delete()
            for k, v in filters.items():
                q = q.eq(k, v)
            return q.execute()
        elif action == "select":
            q = query.select("*")
            if filters:
                for k, v in filters.items():
                    q = q.eq(k, v)
            if order_by:
                q = q.order(order_by, desc=desc)
            return q.execute().data
    except Exception as e:
        print(f"Supabase Operational Error: {e}")
        return [] if action == "select" else None

def get_dm_partners(username: str):
    try:
        res = supabase.rpc("get_dm_partners", {"user_profile": username}).execute()
        return [row['partner'] for row in res.data] if res.data else []
    except Exception:
        # Fallback raw selection filter parsing if custom RPC isn't deployed yet
        dms = supabase.table("dms").select("user_from, user_to").execute().data
        partners = set()
        for d in dms:
            if d['user_from'] == username: partners.add(d['user_to'])
            if d['user_to'] == username: partners.add(d['user_from'])
        return list(partners)