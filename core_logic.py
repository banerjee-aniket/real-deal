import os
import aiohttp
import urllib.parse
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator
import database as db
import logging
import csv
import io

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CoreLogic")

# --- GENERIC HELPERS ---

def format_currency(amount, currency="USD"):
    return f"${amount:,.2f}" if currency == "USD" else f"{amount:,.2f} {currency}"

# --- PURE LOGIC COMMANDS ---

async def cmd_weather(location: str):
    """
    Fetches weather for a location using wttr.in.
    Returns: dict(status, data, message)
    """
    url = f"https://wttr.in/{location}?format=3"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    return {"status": "success", "data": text.strip(), "message": f"Weather for {location}"}
                else:
                    return {"status": "error", "message": "Could not fetch weather."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def cmd_translate(text: str, target_lang: str):
    """
    Translates text to target language.
    """
    try:
        # Note: GoogleTranslator is synchronous, so we might need to run it in executor if called from async context
        # But here we define the core logic. The caller handles async wrapping if needed, 
        # or we just assume this is fast enough for now or use a different lib.
        # deep_translator makes network requests, so it blocks. 
        # For the bot, we'll wrap this. For dashboard, it's fine.
        translated = GoogleTranslator(source='auto', target=target_lang).translate(text)
        return {
            "status": "success", 
            "data": {"original": text, "translated": translated, "lang": target_lang},
            "message": f"Translated to {target_lang}"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def cmd_worldclock(timezone: str):
    """
    Gets time in a timezone.
    """
    try:
        tz = pytz.timezone(timezone)
        curr_time = datetime.now(tz)
        fmt_time = curr_time.strftime("%Y-%m-%d %H:%M:%S %Z%z")
        city_name = timezone.split('/')[-1].replace('_', ' ')
        return {
            "status": "success",
            "data": {"city": city_name, "time": fmt_time, "timezone": timezone},
            "message": f"Time in {city_name}"
        }
    except pytz.UnknownTimeZoneError:
        return {"status": "error", "message": "Unknown timezone. Try format 'Region/City' (e.g., Europe/London)."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

async def cmd_currency(amount: float, from_currency: str, to_currency: str):
    """
    Converts currency.
    """
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()
    
    if len(from_currency) != 3 or len(to_currency) != 3:
        return {"status": "error", "message": "Currency codes must be 3 letters."}

    try:
        url = f"https://open.er-api.com/v6/latest/{from_currency}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                data = await resp.json()
                if data.get("result") == "success":
                    rate = data["rates"].get(to_currency)
                    if rate:
                        converted = amount * rate
                        return {
                            "status": "success",
                            "data": {
                                "from": from_currency,
                                "to": to_currency,
                                "original_amount": amount,
                                "converted_amount": converted,
                                "rate": rate
                            },
                            "message": f"{amount} {from_currency} = {converted:.2f} {to_currency}"
                        }
                    else:
                        return {"status": "error", "message": f"Currency code {to_currency} not found."}
                else:
                    return {"status": "error", "message": "Could not fetch exchange rates."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- BUSINESS LOGIC COMMANDS (Complex) ---

def logic_expense_settle(trip_name: str):
    """
    Calculates settlement plan for expenses.
    """
    expenses_data = db.load_expenses(trip_name)
    if not expenses_data["entries"]:
        return {"status": "error", "message": "No expenses to settle."}

    # 1. Calculate Totals
    total = 0
    paid_by = {}
    for e in expenses_data["entries"]:
        amt = float(e['amount'])
        total += amt
        payer = e['payer']
        paid_by[payer] = paid_by.get(payer, 0) + amt
        
    participants = list(paid_by.keys())
    if not participants:
         return {"status": "error", "message": "No participants found."}
         
    share_per_person = total / len(participants)
    
    # 2. Calculate Balances
    balances = {}
    for p in participants:
        paid = paid_by.get(p, 0)
        balance = paid - share_per_person
        balances[p] = balance
        
    # 3. Generate Plan
    debtors = []
    creditors = []
    
    for p, bal in balances.items():
        if bal < -0.01: # Owe
            debtors.append({'person': p, 'amount': -bal})
        elif bal > 0.01: # Owed
            creditors.append({'person': p, 'amount': bal})
            
    debtors.sort(key=lambda x: x['amount'], reverse=True)
    creditors.sort(key=lambda x: x['amount'], reverse=True)
    
    plan = []
    i = 0
    j = 0
    
    while i < len(debtors) and j < len(creditors):
        debtor = debtors[i]
        creditor = creditors[j]
        
        amount = min(debtor['amount'], creditor['amount'])
        
        plan.append({
            "from": debtor['person'],
            "to": creditor['person'],
            "amount": amount
        })
        
        debtor['amount'] -= amount
        creditor['amount'] -= amount
        
        if debtor['amount'] < 0.01: i += 1
        if creditor['amount'] < 0.01: j += 1
        
    return {
        "status": "success",
        "data": {
            "total": total,
            "per_person": share_per_person,
            "participants": participants,
            "plan": plan
        },
        "message": "Settlement calculated."
    }

def logic_trip_summary(trip_name: str):
    """
    Aggregates trip stats.
    """
    trip = db.get_trip(trip_name)
    if not trip:
        return {"status": "error", "message": f"Trip {trip_name} not found."}

    items = db.get_packing_items(trip_name)
    expenses_data = db.load_expenses(trip_name)
    expenses = expenses_data.get("entries", [])
    reminders = db.get_reminders(trip_name)
    
    total_spend = sum(float(e['amount']) for e in expenses)
    
    spenders = {}
    for e in expenses:
        # Check if user_name exists, otherwise use payer
        payer = e.get('payer', e.get('user_name', 'Unknown'))
        spenders[payer] = spenders.get(payer, 0) + float(e['amount'])
    
    top_spender = max(spenders, key=spenders.get) if spenders else "None"
    top_amount = spenders[top_spender] if spenders else 0

    return {
        "status": "success",
        "data": {
            "trip": trip,
            "packing_count": len(items),
            "total_spend": total_spend,
            "top_spender": top_spender,
            "top_spender_amount": top_amount,
            "reminder_count": len(reminders)
        },
        "message": "Summary generated."
    }

def logic_itinerary(action: str, trip_name: str, **kwargs):
    """
    Manages itinerary items.
    Actions: add, view, delete
    """
    if action == "add":
        title = kwargs.get("title")
        start_time = kwargs.get("start_time")
        if not title or not start_time:
            return {"status": "error", "message": "Title and Start Time required."}
        
        end_time = kwargs.get("end_time")
        location = kwargs.get("location")
        notes = kwargs.get("notes")
        assigned_to = kwargs.get("assigned_to")
        
        # Handle datetime conversion
        if isinstance(start_time, str):
            try:
                start_time = datetime.strptime(start_time, "%Y-%m-%d %H:%M")
            except ValueError:
                return {"status": "error", "message": "Invalid start_time format. Use YYYY-MM-DD HH:MM"}

        if isinstance(end_time, str) and end_time:
             try:
                end_time = datetime.strptime(end_time, "%Y-%m-%d %H:%M")
             except ValueError:
                 pass 

        try:
            db.add_itinerary_item(trip_name, title, start_time, end_time, location, notes, assigned_to)
            return {"status": "success", "message": f"Added {title} to itinerary.", "data": {"title": title}}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif action == "view":
        items = db.get_itinerary(trip_name)
        if not items:
            return {"status": "success", "data": [], "message": "Itinerary is empty."}
        return {"status": "success", "data": items, "message": f"Found {len(items)} items."}

    elif action == "delete":
        item_id = kwargs.get("item_id")
        if not item_id:
            return {"status": "error", "message": "Item ID required."}
        
        try:
            db.delete_itinerary_item(item_id)
            return {"status": "success", "message": f"Deleted item {item_id}."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    return {"status": "error", "message": "Invalid action."}

def logic_reminders(action: str, trip_name: str, **kwargs):
    """
    Manages reminders.
    Actions: add, list, delete
    """
    if action == "add":
        message = kwargs.get("message")
        remind_at = kwargs.get("remind_at") # datetime or str
        user_id = kwargs.get("user_id")
        channel_id = kwargs.get("channel_id")
        
        if not message or not remind_at:
             return {"status": "error", "message": "Message and Time required."}
             
        if isinstance(remind_at, str):
            try:
                remind_at = datetime.strptime(remind_at, "%Y-%m-%d %H:%M")
            except ValueError:
                return {"status": "error", "message": "Invalid time format. Use YYYY-MM-DD HH:MM"}
                
        if remind_at < datetime.now():
             return {"status": "error", "message": "Cannot set reminder in the past!"}
             
        try:
            db.add_reminder(trip_name, user_id, channel_id, message, remind_at)
            return {"status": "success", "message": f"Reminder set for {remind_at}."}
        except Exception as e:
            return {"status": "error", "message": str(e)}
            
    elif action == "list":
        reminders = db.get_reminders(trip_name)
        if not reminders:
            return {"status": "success", "data": [], "message": "No reminders set."}
        return {"status": "success", "data": reminders, "message": f"Found {len(reminders)} reminders."}
        
    elif action == "delete":
        reminder_id = kwargs.get("reminder_id")
        if not reminder_id:
            return {"status": "error", "message": "Reminder ID required."}
        try:
            db.delete_reminder(reminder_id)
            return {"status": "success", "message": f"Deleted reminder {reminder_id}."}
        except Exception as e:
            return {"status": "error", "message": str(e)}
            
    return {"status": "error", "message": "Invalid action."}

def logic_packing_template(trip_name: str, template_name: str):
    """
    Applies a packing template.
    """
    templates = {
        "beach": ["Sunscreen", "Swimwear", "Beach Towel", "Sunglasses", "Flip Flops", "Hat", "Water Bottle"],
        "ski": ["Ski Jacket", "Thermals", "Gloves", "Goggles", "Beanie", "Thick Socks", "Scarves"],
        "camping": ["Tent", "Sleeping Bag", "Flashlight", "Insect Repellent", "First Aid Kit", "Matches", "Power Bank"],
        "city": ["Walking Shoes", "Power Bank", "Umbrella", "Daypack", "Formal Outfit", "City Map/App"],
        "generic": ["Toiletries", "Chargers", "Underwear", "Socks", "Pajamas", "Travel Documents", "Medications"]
    }
    
    template_name = template_name.lower()
    if template_name not in templates:
        return {"status": "error", "message": f"Unknown template. Available: {', '.join(templates.keys())}"}
        
    added_count = 0
    current_items = [i['item'].lower() for i in db.get_packing_items(trip_name)]
    
    for p_item in templates[template_name]:
        if p_item.lower() not in current_items:
            db.add_packing_item(trip_name, p_item)
            added_count += 1
            
    return {"status": "success", "data": {"added": added_count}, "message": f"Added {added_count} items from {template_name} template."}

def logic_packing(action: str, trip_name: str, **kwargs):
    """
    Manages packing list.
    Actions: add, remove, list, claim
    """
    if action == "add":
        item = kwargs.get("item")
        if not item:
            return {"status": "error", "message": "Item name required."}
            
        current_items = db.get_packing_items(trip_name)
        if any(i["item"].lower() == item.lower() for i in current_items):
             return {"status": "error", "message": f"Item '{item}' already exists."}
             
        db.add_packing_item(trip_name, item)
        return {"status": "success", "message": f"Added {item}."}

    elif action == "remove":
        item = kwargs.get("item")
        if not item:
             return {"status": "error", "message": "Item name required."}
             
        current_items = db.get_packing_items(trip_name)
        item_id = next((i["id"] for i in current_items if i["item"].lower() == item.lower()), None)
        
        if not item_id:
            return {"status": "error", "message": f"Item '{item}' not found."}
            
        db.delete_packing_item(item_id)
        return {"status": "success", "message": f"Removed {item}."}

    elif action == "delete":
        item_id = kwargs.get("item_id")
        if not item_id:
             return {"status": "error", "message": "Item ID required."}
        db.delete_packing_item(item_id)
        return {"status": "success", "message": "Item deleted."}

    elif action == "list":
        items = db.get_packing_items(trip_name)
        return {"status": "success", "data": items, "message": f"Found {len(items)} items."}

    elif action == "claim":
        item = kwargs.get("item")
        user = kwargs.get("user") # display_name
        if not item or not user:
             return {"status": "error", "message": "Item and User required."}
             
        current_items = db.get_packing_items(trip_name)
        found_item = next((i for i in current_items if i["item"].lower() == item.lower()), None)
        
        if not found_item:
             return {"status": "error", "message": f"Item '{item}' not found."}
             
        if found_item.get("claimed_by"):
             return {"status": "error", "message": f"Already claimed by {found_item['claimed_by']}."}
             
        db.claim_packing_item(found_item["id"], user)
        return {"status": "success", "message": f"{item} claimed by {user}."}
        
    return {"status": "error", "message": "Invalid action."}

def logic_expense(action: str, trip_name: str, **kwargs):
    """
    Manages expenses.
    Actions: log, view, summary
    """
    if action == "log":
        amount = kwargs.get("amount")
        description = kwargs.get("description")
        payer = kwargs.get("payer")
        
        if not amount or not description or not payer:
             return {"status": "error", "message": "Amount, Description, and Payer required."}
        
        try:
            amount = float(amount)
        except:
             return {"status": "error", "message": "Amount must be a number."}
             
        date = kwargs.get("date")
        if not date:
            date = datetime.now().isoformat()
            
        db.add_expense(trip_name, payer, amount, description, date)
        return {"status": "success", "message": f"Logged ${amount} for {description}."}

    elif action == "view" or action == "export":
        expenses_data = db.load_expenses(trip_name)
        return {"status": "success", "data": expenses_data, "message": f"Found {len(expenses_data['entries'])} expenses."}
        
    elif action == "summary":
         expenses_data = db.load_expenses(trip_name)
         entries = expenses_data.get("entries", [])
         
         if not entries:
             return {"status": "success", "data": {"total": 0, "breakdown": {}}, "message": "No expenses."}
             
         total = sum(float(e['amount']) for e in entries)
         breakdown = {}
         for e in entries:
             payer = e['payer']
             breakdown[payer] = breakdown.get(payer, 0) + float(e['amount'])
             
         return {
             "status": "success", 
             "data": {"total": total, "breakdown": breakdown}, 
             "message": "Expense summary generated."
         }

    return {"status": "error", "message": "Invalid action."}

def logic_trip(action: str, trip_name: str = None, **kwargs):
    """
    Manages trips and countdowns.
    Actions: create (or set), list, get (or show), delete
    """
    if action in ["create", "set"]:
        if not trip_name:
             return {"status": "error", "message": "Trip name required."}
             
        date = kwargs.get("date") # YYYY-MM-DD
        itinerary_channel_id = kwargs.get("itinerary_channel_id")
        
        if date and date != "Pending":
            try:
                # Validate date format
                target_date = datetime.strptime(date, "%Y-%m-%d")
                if target_date < datetime.now():
                    return {"status": "error", "message": "Date has already passed!"}
            except ValueError:
                return {"status": "error", "message": "Invalid date format. Use YYYY-MM-DD."}
        else:
            if not date:
                date = "Pending"
            
        try:
            db.create_trip(trip_name, date, itinerary_channel_id)
            return {"status": "success", "message": f"Trip {trip_name} set for {date}."}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    elif action == "list":
        trips = db.get_all_trips()
        if not trips:
            return {"status": "success", "data": [], "message": "No trips found."}
            
        # Calculate days left for each
        result_list = []
        for t in trips:
            try:
                if t['date'] and t['date'] != "Pending":
                    d = datetime.strptime(t['date'], "%Y-%m-%d")
                    rem = (d - datetime.now()).days + 1
                    t['days_left'] = rem
                else:
                    t['days_left'] = None
                result_list.append(t)
            except:
                t['days_left'] = None
                result_list.append(t)
                
        # Sort by date
        result_list.sort(key=lambda x: x['date'] if x['date'] != "Pending" else "9999-99-99")
        
        return {"status": "success", "data": result_list, "message": f"Found {len(trips)} trips."}

    elif action in ["get", "show"]:
        if not trip_name:
             return {"status": "error", "message": "Trip name required."}
             
        trip = db.get_trip(trip_name)
        if not trip:
            return {"status": "error", "message": f"Trip {trip_name} not found."}
            
        try:
            if trip['date'] and trip['date'] != "Pending":
                d = datetime.strptime(trip['date'], "%Y-%m-%d")
                rem = (d - datetime.now()).days + 1
                trip['days_left'] = rem
            else:
                trip['days_left'] = None
        except:
            trip['days_left'] = None
            
        return {"status": "success", "data": trip, "message": f"Trip {trip_name} details."}

    elif action == "delete":
         if not trip_name:
              return {"status": "error", "message": "Trip name required."}
              
         try:
             db.delete_trip(trip_name)
             return {"status": "success", "message": f"Deleted trip {trip_name}."}
         except Exception as e:
             return {"status": "error", "message": str(e)}

    return {"status": "error", "message": "Invalid action."}

def logic_poll(action: str, trip_name: str = None, **kwargs):
    """Manages polls (advanced). Actions: create, vote, results"""
    if action == "create":
        question = kwargs.get("question")
        options = kwargs.get("options") # list of strings
        creator_id = kwargs.get("creator_id")
        expires_at = kwargs.get("expires_at")
        
        if not all([trip_name, question, options, creator_id]):
            return {"status": "error", "message": "Missing required fields."}

        poll = db.create_poll(trip_name, question, options, creator_id, expires_at)
        if poll:
            return {"status": "success", "data": poll, "message": "Poll created."}
        return {"status": "error", "message": "Failed to create poll."}
        
    elif action == "vote":
        poll_id = kwargs.get("poll_id")
        user_id = kwargs.get("user_id")
        option_index = kwargs.get("option_index")
        weight = kwargs.get("weight", 1)
        
        success = db.vote_poll(poll_id, user_id, option_index, weight)
        if success:
             results = db.get_poll_results(poll_id)
             return {"status": "success", "data": results, "message": "Vote recorded."}
        return {"status": "error", "message": "Failed to vote."}
        
    elif action == "results":
        poll_id = kwargs.get("poll_id")
        results = db.get_poll_results(poll_id)
        return {"status": "success", "data": results, "message": "Poll results."}
        
    return {"status": "error", "message": "Invalid action."}

def logic_location(action: str, trip_name: str, **kwargs):
    """Manages locations and checkins. Actions: add, list, checkin, latest_checkins"""
    if action == "add":
        name = kwargs.get("name")
        type_ = kwargs.get("type")
        address = kwargs.get("address")
        url = kwargs.get("url")
        added_by = kwargs.get("added_by")
        
        if not all([name, type_]):
             return {"status": "error", "message": "Name and Type are required."}
             
        res = db.add_location(trip_name, name, address, url, type_, added_by)
        if res:
            return {"status": "success", "data": res, "message": f"Added location {name}."}
        return {"status": "error", "message": "Failed to add location."}
        
    elif action == "list":
        locs = db.get_locations(trip_name)
        return {"status": "success", "data": locs, "message": f"Found {len(locs)} locations."}
        
    elif action == "checkin":
        user_id = kwargs.get("user_id")
        user_name = kwargs.get("user_name")
        location_id = kwargs.get("location_id")
        
        db.check_in_user(trip_name, user_id, user_name, location_id)
        return {"status": "success", "message": "Checked in!"}
        
    elif action == "latest_checkins":
        checkins = db.get_latest_checkins(trip_name)
        return {"status": "success", "data": checkins, "message": "Latest checkins."}

    return {"status": "error", "message": "Invalid action."}

def logic_memory(action: str, trip_name: str, **kwargs):
    """Manages memories. Actions: add, list"""
    if action == "add":
        url = kwargs.get("url")
        caption = kwargs.get("caption")
        user_id = kwargs.get("user_id")
        day_number = kwargs.get("day_number")
        
        db.add_memory(trip_name, url, caption, user_id, day_number)
        return {"status": "success", "message": "Memory added."}
        
    elif action == "list":
        day_filter = kwargs.get("day_filter")
        mems = db.get_memories(trip_name, day_filter)
        return {"status": "success", "data": mems, "message": f"Found {len(mems)} memories."}
        
    return {"status": "error", "message": "Invalid action."}

# --- REGISTRY ---

def logic_feedback(action: str, **kwargs):
    """Manages feedback. Actions: submit"""
    if action == "submit":
        user = kwargs.get("user")
        message = kwargs.get("message")
        if not message:
             return {"status": "error", "message": "Message required."}
        
        success = db.submit_feedback(user, message)
        if success:
            return {"status": "success", "message": "Feedback submitted. Thank you!"}
        return {"status": "error", "message": "Failed to submit feedback."}
    return {"status": "error", "message": "Invalid action."}

def logic_decide(options: list):
    """Randomly picks an option."""
    import random
    if not options:
        return {"status": "error", "message": "No options provided."}
    choice = random.choice(options)
    return {"status": "success", "data": choice, "message": f"I picked {choice}."}

COMMAND_REGISTRY = {
    "weather": cmd_weather,
    "translate": cmd_translate,
    "worldclock": cmd_worldclock,
    "currency": cmd_currency,
    "settle": logic_expense_settle,
    "summary": logic_trip_summary,
    "packing_template": logic_packing_template,
    "packing": logic_packing,
    "itinerary": logic_itinerary,
    "reminders": logic_reminders,
    "expense": logic_expense,
    "trip": logic_trip,
    "poll": logic_poll,
    "location": logic_location,
    "memory": logic_memory,
    "feedback": logic_feedback,
    "decide": lambda **kwargs: logic_decide(kwargs.get('options', []))
}

def get_command(name):
    return COMMAND_REGISTRY.get(name)
