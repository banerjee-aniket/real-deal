# Real Deal Travel Bot 🌍✈️

A powerful Discord bot designed to streamline group trip planning. From creating trip itineraries and tracking expenses to collaborative packing lists and real-time currency conversion, this bot acts as your central "Mission Control" for travel.

## ✨ Features

*   **Trip Management**: Automatically creates organized categories and channels for each trip (chat, logistics, itinerary, budget).
*   **Expense Tracking**: Log expenses, split costs, and view budget summaries.
*   **Collaborative Packing**: Shared packing lists where users can add and check off items.
*   **Smart Reminders**: Set time-based reminders for important deadlines or events.
*   **Currency Converter**: Real-time exchange rates for international travel.
*   **Trip Dashboard**: A live-updating summary of your trip status (countdown, budget, reminders).
*   **Local Brain**: Basic NLP capabilities for conversational interaction (experimental).
*   **Admin Tools**: Orphan channel cleanup and module configuration.

## 🛠️ Commands

### 🚀 Trip Planning
*   `/newtrip [name] [date] [location]`: Create a new trip with a dedicated category and channels.
*   `/join [trip_name]`: Join an existing trip to get access to its channels.
*   `/leave [trip_name]`: Leave a trip.
*   `/summary [trip_name]`: View a statistical summary (budget, packing status, countdown).

### 💰 Finance & Logistics
*   `/expenses [action] [amount] [description]`: Manage expenses (add, list, delete).
*   `/currency [amount] [from] [to]`: Convert currency (e.g., `/currency 100 USD EUR`).
*   `/packing [action] [item]`: Manage packing lists (add, check, list).

### ⏰ Productivity
*   `/remind [action] [message] [time]`: Set reminders for yourself or the group.
*   `/dashboard [trip_name]`: Create a live-updating dashboard message in the channel.

### ⚙️ Admin & Setup
*   `/setup`: Initialize server roles (Traveler, Planner, etc.) and permissions.
*   `/config [module] [state]`: Enable or disable specific bot modules.
*   `/cleanup_orphans`: Delete channels that are not assigned to any category.
*   `!sync`: Emergency text command to sync slash commands if they don't appear.

## 📦 Installation & Setup

1.  **Clone the repository**
2.  **Install Dependencies**:
    ```bash
    pip install discord.py supabase python-dotenv aiohttp scikit-learn numpy
    ```
3.  **Environment Variables**:
    Create a `.env` file with the following:
    ```env
    DISCORD_TOKEN=your_discord_bot_token
    SUPABASE_URL=your_supabase_url
    SUPABASE_KEY=your_supabase_key
    ```
4.  **Run the Bot**:
    ```bash
    python bot.py
    ```

## 🧠 Local Brain (Experimental)
The bot features a local "brain" using `scikit-learn` (TF-IDF + Logistic Regression) to understand basic intents in natural language. It can detect when you're planning a trip and offer to create one for you.

## 📝 License
[MIT](LICENSE)
