from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import core_logic
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.route('/')
def index():
    res = core_logic.logic_trip("list")
    trips = res['data'] if res['status'] == 'success' else []
    return render_template('index.html', trips=trips)

@app.route('/trip/<trip_name>')
def trip_detail(trip_name):
    res = core_logic.logic_trip("get", trip_name)
    if res['status'] != 'success':
        flash(f"Trip {trip_name} not found.", "error")
        return redirect(url_for('index'))
    trip = res['data']
    
    res_pack = core_logic.logic_packing("list", trip_name)
    packing = res_pack['data'] if res_pack['status'] == 'success' else []
    
    res_exp = core_logic.logic_expense("view", trip_name)
    expenses = res_exp['data']['entries'] if res_exp['status'] == 'success' else []
    
    res_itin = core_logic.logic_itinerary("view", trip_name)
    itinerary = res_itin['data'] if res_itin['status'] == 'success' else []
    
    res_rem = core_logic.logic_reminders("list", trip_name)
    reminders = res_rem['data'] if res_rem['status'] == 'success' else []
    
    # Calculate totals
    total_budget = sum(float(e['amount']) for e in expenses)
    
    return render_template('trip.html', 
                           trip=trip, 
                           packing=packing, 
                           expenses=expenses, 
                           itinerary=itinerary,
                           reminders=reminders,
                           total_budget=total_budget)

# --- ACTIONS ---

@app.route('/create_trip', methods=['POST'])
def create_trip():
    name = request.form.get('name')
    date = request.form.get('date')
    
    if not name or not date:
        flash("Name and Date are required!", "error")
        return redirect(url_for('index'))
        
    # Check if exists
    if core_logic.logic_trip("get", name)['status'] == 'success':
        flash(f"Trip '{name}' already exists!", "error")
        return redirect(url_for('index'))
        
    res = core_logic.logic_trip("create", name, date=date)
    if res['status'] == 'success':
        flash(f"Trip '{name}' created successfully! (Run /sync in Discord to create channels)", "success")
    else:
        flash(f"Error: {res['message']}", "error")
        
    return redirect(url_for('index'))

@app.route('/delete_trip/<trip_name>')
def delete_trip(trip_name):
    core_logic.logic_trip("delete", trip_name)
    flash(f"Trip '{trip_name}' deleted.", "success")
    return redirect(url_for('index'))

@app.route('/trip/<trip_name>/add_item', methods=['POST'])
def add_packing_item(trip_name):
    item = request.form.get('item')
    if item:
        core_logic.logic_packing("add", trip_name, item=item)
        flash(f"Added {item} to packing list.", "success")
    return redirect(url_for('trip_detail', trip_name=trip_name))

@app.route('/delete_item/<int:item_id>')
def delete_packing_item(item_id):
    # trip_name is not needed for delete by ID
    core_logic.logic_packing("delete", "", item_id=item_id)
    return redirect(request.referrer or url_for('index'))

@app.route('/trip/<trip_name>/add_expense', methods=['POST'])
def add_expense(trip_name):
    description = request.form.get('description')
    amount = request.form.get('amount')
    payer = request.form.get('payer')
    date = request.form.get('date')
    
    res = core_logic.logic_expense("log", trip_name, payer=payer, amount=amount, description=description, date=date)
    if res['status'] == 'success':
        flash(f"Added expense: {description} (${amount})", "success")
    else:
        flash(f"Error: {res['message']}", "error")
        
    return redirect(url_for('trip_detail', trip_name=trip_name))

# --- API ENDPOINTS ---

import asyncio
import inspect

@app.route('/api/execute', methods=['POST'])
async def api_execute():
    data = request.json
    command = data.get('command')
    args = data.get('args', {})
    
    cmd_func = core_logic.get_command(command)
    if not cmd_func:
        return jsonify({"status": "error", "message": f"Command {command} not found."}), 404
        
    try:
        if command in ["trip", "packing", "expense", "itinerary", "reminders", "poll", "location", "memory"]:
            action = args.pop('action', None)
            trip_name = args.pop('trip_name', None)
            if not action:
                return jsonify({"status": "error", "message": "Action required."}), 400
            result = cmd_func(action, trip_name, **args)
        else:
            result = cmd_func(**args)
            
        if inspect.iscoroutine(result):
            result = await result
            
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/trips', methods=['GET'])
def api_list_trips():
    return jsonify(core_logic.logic_trip("list"))

@app.route('/api/trips', methods=['POST'])
def api_create_trip():
    data = request.json
    name = data.get('name')
    date = data.get('date')
    return jsonify(core_logic.logic_trip("create", name, date=date))

@app.route('/api/trips/<trip_name>', methods=['GET'])
def api_get_trip(trip_name):
    return jsonify(core_logic.logic_trip("get", trip_name))

@app.route('/api/trips/<trip_name>', methods=['DELETE'])
def api_delete_trip(trip_name):
    return jsonify(core_logic.logic_trip("delete", trip_name))

@app.route('/api/trips/<trip_name>/packing', methods=['GET'])
def api_list_packing(trip_name):
    return jsonify(core_logic.logic_packing("list", trip_name))

@app.route('/api/trips/<trip_name>/packing', methods=['POST'])
def api_add_packing(trip_name):
    data = request.json
    item = data.get('item')
    return jsonify(core_logic.logic_packing("add", trip_name, item=item))

@app.route('/api/trips/<trip_name>/expenses', methods=['GET'])
def api_list_expenses(trip_name):
    return jsonify(core_logic.logic_expense("view", trip_name))

@app.route('/api/trips/<trip_name>/expenses', methods=['POST'])
def api_add_expense(trip_name):
    data = request.json
    return jsonify(core_logic.logic_expense("log", trip_name, **data))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=True)
