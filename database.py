import os
import datetime
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

supabase: Client = None
if url and key:
    try:
        supabase = create_client(url, key)
        print("✅ Supabase Connected")
    except Exception as e:
        print(f"❌ Supabase Connection Failed: {e}")

def keep_alive():
    if not supabase: return
    try:
        supabase.table("trips").select("count", count="exact").execute()
        print("💓 Database heartbeat sent.")
    except Exception as e:
        print(f"Heartbeat failed: {e}")

# --- TRIPS ---
def get_all_trips():
    if not supabase: return []
    try:
        response = supabase.table("trips").select("*").execute()
        return response.data
    except Exception as e:
        print(f"Error getting trips: {e}")
        return []

def create_trip(name, date, channel_id=None):
    if not supabase: return
    try:
        data = {"name": name, "date": date}
        if channel_id:
            data["channel_id"] = str(channel_id)
        supabase.table("trips").upsert(data).execute()
    except Exception as e:
        print(f"Error creating trip: {e}")

def delete_trip(name):
    if not supabase: return
    try:
        supabase.table("trips").delete().eq("name", name).execute()
    except Exception as e:
        print(f"Error deleting trip: {e}")

def get_trip(name):
    if not supabase: return None
    try:
        response = supabase.table("trips").select("*").eq("name", name).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error getting trip: {e}")
        return None

def update_trip_dashboard(name, channel_id, message_id):
    if not supabase: return
    try:
        supabase.table("trips").update({
            "dashboard_message_id": str(message_id),
            "channel_id": str(channel_id)
        }).eq("name", name).execute()
    except Exception as e:
        print(f"Error updating trip dashboard: {e}")

def update_trip_channel_id(name, channel_id):
    if not supabase: return
    try:
        supabase.table("trips").update({
            "channel_id": str(channel_id)
        }).eq("name", name).execute()
    except Exception as e:
        print(f"Error updating trip channel_id: {e}")

# --- PACKING ---
def get_packing_items(trip_name):
    if not supabase: return []
    try:
        response = supabase.table("packing_items").select("*").eq("trip_name", trip_name).execute()
        return response.data
    except Exception as e:
        print(f"Error getting packing items: {e}")
        return []

def add_packing_item(trip_name, item):
    if not supabase: return
    try:
        supabase.table("packing_items").insert({"trip_name": trip_name, "item": item, "claimed_by": None}).execute()
    except Exception as e:
        print(f"Error adding packing item: {e}")

def delete_packing_item(item_id):
    if not supabase: return
    try:
        supabase.table("packing_items").delete().eq("id", item_id).execute()
    except Exception as e:
        print(f"Error deleting packing item: {e}")

def remove_packing_item(trip_name, item_name):
    if not supabase: return
    try:
        supabase.table("packing_items").delete().eq("trip_name", trip_name).eq("item", item_name).execute()
        return True
    except Exception as e:
        print(f"Error removing packing item: {e}")
        return False

def claim_packing_item(item_id, user_name):
    if not supabase: return
    try:
        supabase.table("packing_items").update({"claimed_by": user_name}).eq("id", item_id).execute()
    except Exception as e:
        print(f"Error claiming packing item: {e}")

# --- EXPENSES ---
def add_expense(trip_name, payer, amount, description, date):
    if not supabase: return
    try:
        data = {
            "trip_name": trip_name,
            "payer": payer,
            "amount": amount,
            "description": description,
            "date": date
        }
        supabase.table("expenses").insert(data).execute()
    except Exception as e:
        print(f"Error adding expense: {e}")

def load_expenses(trip_name):
    if not supabase: return {"entries": []}
    try:
        response = supabase.table("expenses").select("*").eq("trip_name", trip_name).execute()
        return {"entries": response.data}
    except Exception as e:
        print(f"Error loading expenses: {e}")
        return {"entries": []}

# --- SMART CONTEXT ---
def set_active_trip(user_id, trip_name):
    if not supabase: return
    try:
        data = {"user_id": str(user_id), "active_trip": trip_name}
        supabase.table("user_settings").upsert(data).execute()
    except Exception as e:
        print(f"Error setting active trip: {e}")

def get_active_trip(user_id):
    if not supabase: return None
    try:
        response = supabase.table("user_settings").select("active_trip").eq("user_id", str(user_id)).execute()
        return response.data[0]['active_trip'] if response.data else None
    except Exception as e:
        print(f"Error getting active trip: {e}")
        return None

# --- ITINERARY ---
def add_itinerary_item(trip_name, title, start_time, end_time=None, location=None, notes=None, assigned_to=None):
    if not supabase: return
    try:
        data = {
            "trip_name": trip_name,
            "title": title,
            "start_time": start_time,
            "end_time": end_time,
            "location": location,
            "notes": notes,
            "assigned_to": assigned_to
        }
        supabase.table("itinerary").insert(data).execute()
    except Exception as e:
        print(f"Error adding itinerary: {e}")

def get_itinerary(trip_name):
    if not supabase: return []
    try:
        response = supabase.table("itinerary").select("*").eq("trip_name", trip_name).order("start_time").execute()
        return response.data
    except Exception as e:
        print(f"Error getting itinerary: {e}")
        return []

def delete_itinerary_item(item_id):
    if not supabase: return
    try:
        supabase.table("itinerary").delete().eq("id", item_id).execute()
    except Exception as e:
        print(f"Error deleting itinerary item: {e}")

def get_upcoming_itinerary(trip_name, limit=3):
    if not supabase: return []
    try:
        now = datetime.datetime.now().isoformat()
        response = supabase.table("itinerary").select("*")\
            .eq("trip_name", trip_name)\
            .gte("start_time", now)\
            .order("start_time")\
            .limit(limit)\
            .execute()
        return response.data
    except Exception as e:
        print(f"Error getting upcoming itinerary: {e}")
        return []

# --- REMINDERS ---
def add_reminder(trip_name, user_id, channel_id, message, remind_at):
    if not supabase: return
    try:
        data = {
            "trip_name": trip_name,
            "user_id": str(user_id),
            "channel_id": str(channel_id),
            "message": message,
            "remind_at": remind_at.isoformat()
        }
        supabase.table("reminders").insert(data).execute()
    except Exception as e:
        print(f"Error adding reminder: {e}")

def get_reminders(trip_name):
    if not supabase: return []
    try:
        response = supabase.table("reminders").select("*").eq("trip_name", trip_name).order("remind_at").execute()
        return response.data
    except Exception as e:
        print(f"Error getting reminders: {e}")
        return []

def delete_reminder(reminder_id):
    if not supabase: return
    try:
        supabase.table("reminders").delete().eq("id", reminder_id).execute()
    except Exception as e:
        print(f"Error deleting reminder: {e}")

def get_due_reminders():
    if not supabase: return []
    try:
        now_str = datetime.datetime.now().isoformat()
        response = supabase.table("reminders").select("*").lte("remind_at", now_str).execute()
        return response.data
    except Exception as e:
        print(f"Error getting due reminders: {e}")
        return []

# --- MODULES ---
def get_module_status(guild_id, module_name):
    if not supabase: return True # Default to enabled if DB fails or row missing (we will upsert on toggle)
    try:
        response = supabase.table("server_modules").select("is_enabled")\
            .eq("guild_id", str(guild_id))\
            .eq("module_name", module_name)\
            .execute()
        if response.data:
            return response.data[0]['is_enabled']
        return True # Default enabled
    except Exception as e:
        print(f"Error getting module status: {e}")
        return True

def toggle_module(guild_id, module_name, is_enabled):
    if not supabase: return
    try:
        data = {
            "guild_id": str(guild_id),
            "module_name": module_name,
            "is_enabled": is_enabled
        }
        supabase.table("server_modules").upsert(data).execute()
    except Exception as e:
        print(f"Error toggling module: {e}")


# --- POLLS ---
def create_poll(trip_name, question, options, creator_id, expires_at=None):
    if not supabase: return None
    try:
        data = {
            "trip_name": trip_name,
            "question": question,
            "options": options,
            "creator_id": str(creator_id),
            "is_active": True
        }
        if expires_at:
            data["expires_at"] = expires_at.isoformat()
        response = supabase.table("polls").insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error creating poll: {e}")
        return None

def update_poll_message(poll_id, channel_id, message_id):
    if not supabase: return
    try:
        supabase.table("polls").update({
            "channel_id": str(channel_id),
            "message_id": str(message_id)
        }).eq("id", poll_id).execute()
    except Exception as e:
        print(f"Error updating poll message: {e}")

def vote_poll(poll_id, user_id, option_index, weight=1):
    if not supabase: return False
    try:
        data = {
            "poll_id": poll_id,
            "user_id": str(user_id),
            "option_index": option_index,
            "weight": weight
        }
        supabase.table("poll_votes").upsert(data, on_conflict="poll_id,user_id").execute()
        return True
    except Exception as e:
        print(f"Error voting: {e}")
        return False

def get_poll_results(poll_id):
    if not supabase: return {}
    try:
        votes = supabase.table("poll_votes").select("*").eq("poll_id", poll_id).execute()
        poll = supabase.table("polls").select("options").eq("id", poll_id).single().execute()
        if not poll.data: return {}
        options = poll.data['options']
        
        results = {i: 0 for i in range(len(options))}
        total_votes = 0
        
        for v in votes.data:
            idx = v['option_index']
            w = v.get('weight', 1)
            if idx in results:
                results[idx] += w
                total_votes += w
                
        return {"results": results, "total": total_votes, "options": options}
    except Exception as e:
        print(f"Error getting poll results: {e}")
        return {}

def get_active_polls(trip_name):
    if not supabase: return []
    try:
        response = supabase.table("polls").select("*").eq("trip_name", trip_name).eq("is_active", True).execute()
        return response.data
    except Exception as e:
        print(f"Error getting active polls: {e}")
        return []

# --- LOCATIONS ---
def add_location(trip_name, name, address, url, loc_type, added_by):
    if not supabase: return None
    try:
        data = {
            "trip_name": trip_name,
            "name": name,
            "address": address,
            "url": url,
            "type": loc_type,
            "added_by": added_by
        }
        response = supabase.table("locations").insert(data).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error adding location: {e}")
        return None

def get_locations(trip_name):
    if not supabase: return []
    try:
        response = supabase.table("locations").select("*").eq("trip_name", trip_name).order("type").execute()
        return response.data
    except Exception as e:
        print(f"Error getting locations: {e}")
        return []

def delete_location(location_id):
    if not supabase: return
    try:
        supabase.table("locations").delete().eq("id", location_id).execute()
    except Exception as e:
        print(f"Error deleting location: {e}")

def check_in_user(trip_name, user_id, user_name, location_id):
    if not supabase: return
    try:
        data = {
            "trip_name": trip_name,
            "user_id": str(user_id),
            "user_name": user_name,
            "location_id": location_id,
            "timestamp": datetime.datetime.now().isoformat()
        }
        supabase.table("checkins").insert(data).execute()
    except Exception as e:
        print(f"Error checking in: {e}")

def get_latest_checkins(trip_name):
    if not supabase: return []
    try:
        response = supabase.table("checkins").select("*, locations(name, type)")\
            .eq("trip_name", trip_name)\
            .order("timestamp", desc=True)\
            .limit(50)\
            .execute()
            
        checkins = response.data
        latest = {}
        for c in checkins:
            uid = c['user_id']
            if uid not in latest:
                latest[uid] = c
        return list(latest.values())
    except Exception as e:
        print(f"Error getting checkins: {e}")
        return []

# --- MEMORIES ---
def add_memory(trip_name, url, caption, user_id, day_number=None):
    if not supabase: return
    try:
        data = {
            "trip_name": trip_name,
            "url": url,
            "caption": caption,
            "user_id": str(user_id),
            "day_number": day_number
        }
        supabase.table("memories").insert(data).execute()
    except Exception as e:
        print(f"Error adding memory: {e}")

def get_memories(trip_name, day_filter=None):
    if not supabase: return []
    try:
        query = supabase.table("memories").select("*").eq("trip_name", trip_name)
        if day_filter is not None:
            query = query.eq("day_number", day_filter)
        
        response = query.order("created_at", desc=True).execute()
        return response.data
    except Exception as e:
        print(f"Error getting memories: {e}")
        return []
