import json
import os
import re  # <--- 1. Added Regex import
import ollama
from pypdf import PdfReader
from database import save_resume_data

def parse_resume(pdf_path):
    # 1. Load PDF
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"

    # 2. Prompt
    prompt = f"""
    You are a resume parsing AI.
    Extract the following details from the resume text and be comprehensive.
    - Full Name (full_name)
    - Top 10 Skills (skills - list format)
    - Total Years of Experience (experience_years - integer)
    - Current Job Role (current_role)
    - Email (email)

    Important instructions:
    - Return ONLY a valid JSON object.
    - Do not include any conversational text before or after the JSON.

    Resume Text: {text}
    """
    
    print("⏳ Asking Ollama to parse resume...")
    response = ollama.chat(model='llama3', messages=[{'role': 'user', 'content': prompt}])
    raw_content = response['message']['content'].strip()
    
    # 3. IMPROVED CLEANING LOGIC (The Fix)
    try:
        # This regex finds the first '{' and the last '}' and extracts everything in between
        # re.DOTALL allows the '.' to match newlines
        match = re.search(r'(\{.*\})', raw_content, re.DOTALL)
        
        if match:
            clean_content = match.group(1)
            print("✨ Clean JSON found!")
        else:
            print(f"❌ No JSON object found in LLM response. Raw output: {raw_content}")
            raise ValueError("LLM did not return a valid JSON object.")

        parsed_data = json.loads(clean_content)
        
        # Save to DB
        save_resume_data(parsed_data)
        return parsed_data

    except json.JSONDecodeError as e:
        print(f"❌ JSON Decode Error: {e}")
        print(f"DEBUG: The content that failed was: {raw_content}")
        raise e
    except Exception as e:
        print(f"❌ An error occurred: {e}")
        raise e

if __name__ == "__main__":
    # Use absolute path to avoid issues
    base_dir = os.path.dirname(os.path.abspath(__file__))
    pdf_path = os.path.join(base_dir, "my_resume.pdf")

    if not os.path.exists(pdf_path):
        print(f"❌ Error: File not found at {pdf_path}")
    else:
        try:
            data = parse_resume(pdf_path)
            print("✅ Resume parsed and saved successfully!")
            print(json.dumps(data, indent=2))
        except Exception as e:
            print(f"💥 Script failed: {e}")