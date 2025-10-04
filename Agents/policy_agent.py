import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def answer_policy_question(question):
    policy_path = os.path.join("knowledge", "policy.txt")
    if not os.path.exists(policy_path):
        return "⚠️ Policy file not found."

    with open(policy_path, "r") as f:
        policy_text = f.read()

    prompt = f"""
You are an HR policy assistant.
Refer only to this company policy text and answer truthfully.

Policy:
\"\"\"{policy_text}\"\"\"

Question: {question}

If the answer isn’t covered, reply "Not covered in current policy."
"""
    try:
        response = client.responses.create(model="gpt-4o-mini", input=prompt, temperature=0.2)
        return response.output_text.strip()
    except Exception as e:
        return f"Error answering policy: {e}"
