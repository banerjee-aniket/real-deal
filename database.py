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
        response = supabase.table("itinerary").select("*").eq("trip_name", trip_name).gte("start_time", datetime.datetime.now().isoformat()).order("start_time").limit(limit).execute()
        return response.data
    except Exception as e:
        print(f"Error getting upcoming itinerary: {e}")
        return []

# --- REMINDERS ---
def add_reminder(trip_name, message, remind_at):
    if not supabase: return
    try:
        data = {"trip_name": trip_name, "message": message, "remind_at": remind_at, "completed": False}
        supabase.table("reminders").insert(data).execute()
    except Exception as e:
        print(f"Error adding reminder: {e}")

def get_reminders(trip_name):
    if not supabase: return []
    try:
        response = supabase.table("reminders").select("*").eq("trip_name", trip_name).eq("completed", False).execute()
        return response.data
    except Exception as e:
        print(f"Error getting reminders: {e}")
        return []

def mark_reminder_completed(reminder_id):
    if not supabase: return
    try:
        supabase.table("reminders").update({"completed": True}).eq("id", reminder_id).execute()
    except Exception as e:
        print(f"Error marking reminder completed: {e}")

# --- FEEDBACK ---
def submit_feedback(user_name, message):
    if not supabase: return
    try:
        data = {
            "user_name": user_name,
            "message": message,
            "created_at": datetime.datetime.now().isoformat()
        }
        supabase.table("feedback").insert(data).execute()
        return True
    except Exception as e:
        print(f"Error submitting feedback: {e}")
        return False

# --- MODULES ---
def get_module_status(guild_id, module_name):
    # For now, default to True as we haven't implemented a module table
    return True
