import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from ollama import chat
import firebase_admin
from firebase_admin import credentials, firestore

# ========================================
# 1. INITIALIZE FIREBASE & FIRESTORE
# ========================================
cred = credentials.Certificate("serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

def load_landmarks_from_firebase():
    print("Fetching marker data from Firebase...")
    markers_ref = db.collection("markers")
    docs = markers_ref.stream()
    
    landmarks_data = {}
    for doc in docs:
        data = doc.to_dict()
        
        name = data.get("landmarkName") or data.get("institutionName") or data.get("name", "Unknown Landmark")
        description = data.get("description") or data.get("info", {}).get("description", "")
        location = data.get("location", "Cebu City, Philippines")
        topics = data.get("topics", ["history", "culture", "landmark"])
        related_people = data.get("related_people", [])

        landmarks_data[doc.id] = {
            "name": name,
            "location": location,
            "description": description,
            "topics": topics,
            "related_people": related_people
        }
        
    if not landmarks_data:
        print("Warning: No documents found in Firestore 'markers' collection.")
        
    return landmarks_data

# Populate LANDMARKS from Firebase 'markers' collection
LANDMARKS = load_landmarks_from_firebase()

# ========================================
# 2. HELPER FUNCTIONS & SCRAPER
# ========================================

BLOCKED_DOMAINS = [
    "facebook.com", "instagram.com", "twitter.com", "x.com", 
    "tiktok.com", "youtube.com", "reddit.com", "pinterest.com", "linkedin.com"
]

def is_question_in_scope(question, conversation_history, selected_landmark):
    """
    Strict binary classifier using Qwen 1.7B.
    Determines if the question is strictly about the selected landmark or its specific historical figures.
    """
    landmark_name = selected_landmark['name']

    prompt = f"""You are an absolute boundary filter.

Active Target Landmark: "{landmark_name}"

User Question: "{question}"

Rules:
- Is the User Question specifically asking about "{landmark_name}" or a person directly tied to its creation/history? -> Answer YES
- Is the User Question asking about ANY OTHER landmark (such as Magellan's Cross, Basilica del Santo Niño, Eiffel Tower, etc.)? -> Answer NO
- Is the User Question asking about recipes, coding, weather, or general trivia? -> Answer NO

Answer with ONLY ONE WORD: YES or NO."""

    try:
        response = chat(
            model="qwen3:1.7b",
            messages=[{"role": "user", "content": prompt}],
            think=False,
            options={"temperature": 0.0, "num_ctx": 512}
        )
        content = response["message"]["content"].strip().upper()
        if "</think>" in content:
            content = content.split("</think>")[-1].strip().upper()

        decision = "YES" in content and "NO" not in content
        print(f"  [SCOPE CHECK] Question: '{question}' | Allowed: {decision} (Model output: {content})")
        return decision
    except Exception as e:
        print(f"  [SCOPE CHECK ERROR]: {e}")
        return False  # Strict default: block if classification fails

def fetch_page(url):
    # Skip social media / non-parsable domains
    if any(domain in url.lower() for domain in BLOCKED_DOMAINS):
        print(f"Skipping social media link: {url}")
        return []

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        response = requests.get(url, timeout=5, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        paragraphs = []
        for paragraph in soup.find_all("p"):
            text = paragraph.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)

        return paragraphs[:30]
    except Exception:
        return []

def get_relevant_paragraphs(paragraphs, question, landmark_context, conversation_context):
    relevance_text = f"{landmark_context}\n{conversation_context}\n{question}"
    question_words = set(
        relevance_text.lower()
        .replace("?", "").replace(",", "").replace(".", "").split()
    )

    relevant = []
    for paragraph in paragraphs:
        paragraph_lower = paragraph.lower()
        score = sum(2 for word in question_words if len(word) > 3 and word in paragraph_lower)
        if score > 0:
            relevant.append((score, paragraph))

    relevant.sort(key=lambda item: item[0], reverse=True)
    return [paragraph for score, paragraph in relevant[:4]]

def generate_search_query(question, conversation_history, selected_landmark):
    if not conversation_history:
        clean_q = question.strip("?!.,:;")
        return f"{selected_landmark['name']} Cebu {clean_q}"

    history_text = ""
    for turn in conversation_history[-3:]:
        history_text += f"User: {turn['question']}\nAI: {turn['answer']}\n"

    reformulate_prompt = f"""You are a search query generator for a historical landmark assistant.

Selected Landmark: {selected_landmark['name']} ({selected_landmark['location']})

Recent Conversation:
{history_text}

User's Question: "{question}"

Task: Rewrite the user's question into a concise, standalone ENGLISH web search query (3 to 6 words).

Rules:
1. If the question is about a specific historical person (e.g., Miguel López de Legazpi), search for THAT PERSON's biography in English (e.g., "Miguel López de Legazpi wife Isabel biography english").
2. Do NOT search in Spanish.
3. Replace pronouns (he, she, his) with exact historical names from context.
4. Output ONLY the search query text with no quotes, explanations, or formatting.
"""

    try:
        response = chat(
            model="qwen3:1.7b",
            messages=[{"role": "user", "content": reformulate_prompt}],
            think=False,
            options={"temperature": 0.1, "num_ctx": 1024}
        )
        query = response["message"]["content"].strip()
        if "</think>" in query:
            query = query.split("</think>")[-1].strip()
        return query
    except Exception as e:
        return f"{selected_landmark['name']} {question}"

# ========================================
# 3. SELECT LANDMARK MENU
# ========================================

print("\nAvailable landmarks:")
landmark_ids = list(LANDMARKS.keys())

for index, landmark_id in enumerate(landmark_ids, start=1):
    landmark = LANDMARKS[landmark_id]
    print(f"{index}. {landmark['name']} ({landmark['location']})")

while True:
    landmark_choice = input("\nSelect a landmark: ")
    try:
        landmark_index = int(landmark_choice) - 1
        if 0 <= landmark_index < len(landmark_ids):
            break
        print("Please select a valid landmark number.")
    except ValueError:
        print("Please enter a number.")

selected_landmark_id = landmark_ids[landmark_index]
selected_landmark = LANDMARKS[selected_landmark_id]

landmark_context = f"""
Landmark: {selected_landmark["name"]}
Location: {selected_landmark["location"]}
Description: {selected_landmark["description"]}
Historical topics: {", ".join(selected_landmark["topics"])}
Related people: {", ".join(selected_landmark["related_people"])}
"""

# Dynamic System Instructions WITH scope guarding
instructions = f"""You are ScenARy AI, a historical guide dedicated STRICTLY to {selected_landmark['name']}.

CRITICAL BOUNDARIES & ACCURACY RULES:
1. ONLY answer questions directly related to {selected_landmark['name']} ({selected_landmark['location']}), its history, architecture, construction, or key historical figures attached to it.
2. HISTORICAL ALIGNMENT & ACCURACY:
   - Match historical relationships accurately. Do NOT confuse mothers, fathers, or relatives with spouses/wives.
   - If the exact wife's name is not explicitly mentioned in the retrieved source text, state clearly: "The retrieved historical records do not specify his wife's name." Never guess or confuse relationships.
3. Keep answers concise, factual, and direct.
4. REFUSAL POLICY: If the user asks about a DIFFERENT landmark (e.g., asking about Magellan's Cross when Fort San Pedro is selected) or general off-topic subjects (recipes, coding, math, general trivia), YOU MUST DECLINE TO ANSWER.
5. Decline using this statement: "I am currently set up as your guide for {selected_landmark['name']}. I can only answer questions related to this landmark!"
6. HISTORICAL ALIGNMENT: Match time periods strictly! Do NOT confuse modern events held at the venue (e.g., mass weddings, concerts, tourist events) with 16th–19th century historical figures.
7. Do not invent historical facts or guess facts not found in retrieved sources.

SOURCE CONFIDENCE:
- Base your answers strictly on retrieved sources and conversation context.
- If the retrieved sources provide limited information, make that clear.

STYLE:
- Answer directly, concisely, and naturally.
- Do not explain your reasoning process.
"""

print(f"\nSelected landmark: {selected_landmark['name']}")

# ========================================
# 4. MAIN CHAT LOOP
# ========================================

conversation_history = []

while True:
    question = input("\nYou: ").strip()

    if question.lower() in ["exit", "quit", "bye"]:
        print("\nSCENARY AI: Goodbye!")
        break

    if not question:
        continue

    # Fast Pre-Check: Detect mentions of other loaded landmarks
    in_scope = is_question_in_scope(question, conversation_history, selected_landmark)

    if not in_scope:
        print("\n" + "=" * 50)
        print("SCENARY AI")
        print("=" * 50)
        print(f"I am currently set up as your guide for {selected_landmark['name']}. I can only answer questions related to this landmark!")
        print("=" * 50)
        continue

    # Build conversation context
    conversation_context = ""
    if conversation_history:
        for turn in conversation_history[-4:]:
            conversation_context += f"Previous question: {turn['question']}\nPrevious answer: {turn['answer']}\n"

    # Web Search
    search_query = generate_search_query(question, conversation_history, selected_landmark)
    print(f"\nSearching for: \"{search_query}\"...")

    search_results = []
    try:
        # Force US English search results to prevent Spanish Wikipedia snippets
        search_results = list(DDGS().text(f"{search_query} english", region="us-en", max_results=6))

        # Filter out non-English URLs (e.g., es.wikipedia.org)
        search_results = [
            r for r in search_results 
            if "es.wikipedia.org" not in r.get("href", "").lower()
        ]
    except Exception as e:
        print(f"Search warning: {e}")

    preferred_domains = [
        "wikipedia.org", "nhcp.gov.ph", "gov.ph", ".edu.ph", "museum", "archive.org", "kahibalo.com"
    ]

    results = sorted(
        search_results,
        key=lambda r: any(domain in r.get("href", "").lower() for domain in preferred_domains),
        reverse=True
    )[:3]

    if not results:
        print("\nSCENARY AI: I couldn't find enough information to answer that question.")
        continue

    # Scrape Content
    source_information = ""
    for result in results:
        title = result.get("title", "Untitled")
        url = result.get("href", "")
        snippet = result.get("body", "")

        print(f"Reading: {title}")
        paragraphs = fetch_page(url)

        relevant_paragraphs = get_relevant_paragraphs(
            paragraphs, question, landmark_context, conversation_context
        )

        if relevant_paragraphs:
            relevant_text = "\n".join(relevant_paragraphs) + f"\n\nSEARCH RESULT DESCRIPTION:\n{snippet}\n"
        else:
            relevant_text = snippet

        source_information += f"\nSOURCE: {title}\nURL: {url}\nRELEVANT INFORMATION:\n{relevant_text}\n"

    # Final Response Generation
    try:
        response = chat(
            model="qwen3:1.7b",
            messages=[
                {"role": "system", "content": instructions},
                {
                    "role": "user",
                    "content": f"Conversation history:\n{conversation_context}\n\nRetrieved information:\n{source_information}\n\nCurrent question:\n{question}"
                }
            ],
            think=False,
            options={"temperature": 0.3, "num_ctx": 2048}
        )

        answer = response["message"]["content"]
        if "</think>" in answer:
            answer = answer.split("</think>")[-1]

        print("\n" + "=" * 50)
        print("SCENARY AI")
        print("=" * 50)
        print(answer.strip())
        print("=" * 50)

        conversation_history.append({
            "question": question,
            "answer": answer.strip()
        })
    except Exception as e:
        print(f"\nError generating response: {e}")