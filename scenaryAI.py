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

LANDMARKS = load_landmarks_from_firebase()

# ========================================
# 2. HELPER FUNCTIONS & SCRAPER
# ========================================

BLOCKED_DOMAINS = [
    "facebook.com", "instagram.com", "twitter.com", "x.com", 
    "tiktok.com", "youtube.com", "reddit.com", "pinterest.com", 
    "linkedin.com", "wikipedia.org", "wikiwand.com"
]

SYNONYM_MAP = {
    "wife": ["spouse", "married", "marry", "marriage", "consort", "bride"],
    "husband": ["spouse", "married", "marry", "marriage", "consort"],
    "parents": ["father", "mother", "born", "son of", "daughter of", "family", "parentage"],
    "father": ["parent", "born", "son of"],
    "mother": ["parent", "born", "son of"],
    "founded": ["built", "established", "constructed", "foundation", "created", "erected"]
}

# === FIX 1: STRICT SCOPE CLASSIFIER PARSING ===
def is_question_in_scope(question, conversation_history, selected_landmark):
    landmark_name = selected_landmark['name']

    prompt = f"""Target Landmark: "{landmark_name}"
User Question: "{question}"

Is this question specifically about "{landmark_name}" or the historical figures directly involved with its creation?

Rules:
- If asking about ANY OTHER landmark (Magellan's Cross, Basilica, Intramuros, Eiffel Tower) -> Answer NO
- If asking about general off-topic items (recipes, coding, math) -> Answer NO
- If asking about "{landmark_name}" or its history/founders -> Answer YES

Reply with ONLY the single word YES or NO."""

    try:
        response = chat(
            model="qwen3:1.7b",
            messages=[{"role": "user", "content": prompt}],
            think=False,
            options={"temperature": 0.0, "num_ctx": 256}
        )
        content = response["message"]["content"].strip().upper()
        if "</think>" in content:
            content = content.split("</think>")[-1].strip().upper()

        # Strict checking: Must start with YES and not contain NO
        decision = content.startswith("YES") and "NO" not in content
        print(f"  [SCOPE CHECK] Question: '{question}' | Allowed: {decision} (Model output: {content})")
        return decision
    except Exception as e:
        print(f"  [SCOPE CHECK ERROR]: {e}")
        return False

def fetch_page(url):
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
    raw_question_words = [
        w.lower().strip("?!.,:;\"'") 
        for w in question.split() 
        if len(w) > 2 and w.lower() not in ["what", "who", "where", "when", "how", "was", "his", "her", "their", "the"]
    ]
    
    target_keywords = set(raw_question_words)
    for word in raw_question_words:
        if word in SYNONYM_MAP:
            target_keywords.update(SYNONYM_MAP[word])

    scored_paragraphs = []
    for paragraph in paragraphs:
        p_lower = paragraph.lower()
        score = sum(5 for kw in target_keywords if kw in p_lower)
        
        if selected_landmark['name'].lower() in p_lower:
            score += 1

        if score > 0:
            scored_paragraphs.append((score, paragraph))

    scored_paragraphs.sort(key=lambda item: item[0], reverse=True)
    return [paragraph for _, paragraph in scored_paragraphs[:6]]

# === FIX 2: UNPOLLUTED SEARCH QUERY GENERATION ===
def generate_search_query(question, conversation_history, selected_landmark):
    # Pass ONLY previous questions (NOT long AI answers) to prevent context keyword pollution
    history_text = ""
    if conversation_history:
        history_text = "\n".join([f"- Previous Question: {turn['question']}" for turn in conversation_history[-3:]])

    reformulate_prompt = f"""Active Landmark: {selected_landmark['name']} ({selected_landmark['location']})

{history_text}

Current User Question: "{question}"

Task: Rewrite the CURRENT User Question into a 3 to 5 word web search query.

Rules:
1. Look ONLY at what the Current User Question is asking right now.
2. If pronouns (he, his, him, it, its) are used, resolve who they refer to from Previous Questions.
3. Always include "{selected_landmark['name']}" if asking about landmark creation or founding.
4. Output ONLY the search query words. No quotes or explanations."""

    try:
        response = chat(
            model="qwen3:1.7b",
            messages=[{"role": "user", "content": reformulate_prompt}],
            think=False,
            options={"temperature": 0.0, "num_ctx": 512}
        )
        query = response["message"]["content"].strip()
        if "</think>" in query:
            query = query.split("</think>")[-1].strip()
        return query
    except Exception:
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

# === FIX 3: VENUE ISOLATION & STRICT REFUSAL INSTRUCTIONS ===
instructions = f"""You are ScenARy AI, a historical guide dedicated STRICTLY to {selected_landmark['name']} in {selected_landmark['location']}.

CRITICAL BOUNDARIES & ACCURACY RULES:
1. ONLY answer questions directly related to {selected_landmark['name']} ({selected_landmark['location']}).
2. VENUE ISOLATION:
   - Stay focused strictly on {selected_landmark['name']} in {selected_landmark['location']}.
   - Do NOT confuse {selected_landmark['name']} with other sites built by the same historical figures in different cities (e.g., do NOT mention Intramuros or Manila when answering about Fort San Pedro in Cebu).
3. SUBJECT CONSISTENCY & ACCURACY:
   - Stay focused strictly on the primary historical figure being asked about. Do NOT attribute facts belonging to secondary figures to the main subject.
4. REFUSAL POLICY:
   - If the user asks about a DIFFERENT landmark (e.g., Magellan's Cross, Basilica, Intramuros, Eiffel Tower), YOU MUST DECLINE TO ANSWER.
   - Decline statement: "I am currently set up as your guide for {selected_landmark['name']}. I can only answer questions related to this landmark!"
5. FALLBACK POLICY:
   - If retrieved sources do not contain the specific detail requested, state clearly: "The retrieved historical records do not provide that specific detail."
6. Keep answers concise, factual, and direct. Do not invent historical facts.
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

    in_scope = is_question_in_scope(question, conversation_history, selected_landmark)

    if not in_scope:
        print("\n" + "=" * 50)
        print("SCENARY AI")
        print("=" * 50)
        print(f"I am currently set up as your guide for {selected_landmark['name']}. I can only answer questions related to this landmark!")
        print("=" * 50)
        continue

    conversation_context = ""
    if conversation_history:
        for turn in conversation_history[-3:]:
            conversation_context += f"Previous question: {turn['question']}\nPrevious answer: {turn['answer']}\n"

    search_query = generate_search_query(question, conversation_history, selected_landmark)
    print(f"\nSearching for: \"{search_query}\"...")

    search_results = []
    try:
        with DDGS() as ddgs:
            search_results = list(ddgs.text(f"{search_query} english", region="us-en", max_results=8))

        search_results = [
            r for r in search_results 
            if not any(domain in r.get("href", "").lower() for domain in BLOCKED_DOMAINS)
        ]
    except Exception as e:
        print(f"Search warning: {e}")

    preferred_domains = [
        "nhcp.gov.ph", "gov.ph", ".edu.ph", "museum", "archive.org", "kahibalo.com"
    ]

    results = sorted(
        search_results,
        key=lambda r: any(domain in r.get("href", "").lower() for domain in preferred_domains),
        reverse=True
    )[:3]

    if not results:
        print("\nSCENARY AI: I couldn't find enough information to answer that question.")
        continue

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
            options={"temperature": 0.1, "num_ctx": 2048}
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