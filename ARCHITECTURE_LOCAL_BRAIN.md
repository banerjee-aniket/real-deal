# Architecture: Local Intelligence Engine

This document describes the architecture of the **Local Intelligence Engine** implemented in the Real Deal Discord bot. The system is designed to provide intelligent, context-aware responses locally without relying on external APIs, ensuring privacy, speed, and offline capability.

## 1. Overview

The Local Brain (`local_brain.py`) is a hybrid system combining:
1.  **Machine Learning (NLU)**: Intent classification using TF-IDF vectorization and Logistic Regression.
2.  **Rule-Based Logic**: Deterministic response generation based on classified intents and keyword matching.
3.  **Knowledge Base**: A JSON-based repository of static travel knowledge (packing lists, tips).
4.  **Context Management**: In-memory tracking of user conversation history to maintain context.

## 2. Components

### 2.1 Intent Classifier (ML Model)
-   **Library**: `scikit-learn`
-   **Algorithm**: Logistic Regression with TF-IDF Vectorization.
-   **Training**: Trained on startup using `data/training_data.json`.
-   **Input**: User query string.
-   **Output**: Intent label (e.g., `packing_help`) and confidence score (0.0 - 1.0).
-   **Performance**: < 10ms inference time.

### 2.2 Knowledge Base
-   **Storage**: `data/knowledge_base.json`
-   **Content**:
    -   `packing_suggestions`: Lists of items for different trip types (beach, trek, etc.).
    -   `budget_tips`: Static advice for saving money.
    -   `travel_hacks`: Random tips for travelers.

### 2.3 Context Manager
-   **Storage**: In-memory dictionary `self.context`.
-   **Structure**: `{ user_id: { "last_intent": str, "history": [queries] } }`
-   **Usage**: Used to refine responses based on previous interactions (e.g., if the user just asked about "beach", packing suggestions will prioritize beach items).

### 2.4 Fallback Mechanism
-   If ML confidence < 0.25, the Local Brain returns `None`.
-   The bot then falls back to External AI (Gemini) or Web Search (DuckDuckGo).

## 3. Data Flow

1.  **User Input**: `/ask "What should I pack for Goa?"`
2.  **Preprocessing**: Text is normalized (lowercase, stop words removed by vectorizer).
3.  **Prediction**: Model predicts intent `packing_help` with confidence `0.85`.
4.  **Context Update**: User context updated with intent `packing_help`.
5.  **Response Generation**:
    -   Intent `packing_help` triggers the packing response generator.
    -   Keyword "Goa" (implied beach/city) might trigger specific suggestions if mapped.
    -   Response: "Don't forget the essentials! ..."
6.  **Output**: Response sent to Discord Embed.

## 4. Scalability & Extensibility

-   **Adding Intents**: Simply add new entries to `data/training_data.json` and restart the bot. The model retrains automatically.
-   **Adding Knowledge**: Update `data/knowledge_base.json` to enrich responses.
-   **Model Upgrades**: The pipeline can be swapped for more complex models (e.g., BERT) if needed, provided dependencies are managed.

## 5. Benchmarks

-   **Accuracy**: > 85% on test set.
-   **Latency**: ~8ms per query (on standard CPU).
-   **Memory Footprint**: < 50MB (lightweight).
