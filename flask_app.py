# Import necessary libraries and modules
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import requests
import logging
from logging.handlers import RotatingFileHandler
from pydantic import BaseModel
from typing import List, Optional
import os

# Define a response model using Pydantic for data validation and settings management
class GetQuestionAndFactsResponse(BaseModel):
    question: str
    facts: Optional[List[str]]
    status: str

# Create a Flask application instance
app = Flask(__name__)
app.secret_key = os.getenv("APP_KEY") # Securely fetch the secret key from environment variables
openai_api_key = os.getenv("OPENAI_API_KEY") # Securely fetch the OpenAI API key from environment variables

# A dictionary to store facts against session IDs
facts_storage = {}

# Configure logging if the app is not in debug mode
if not app.debug:
    handler = RotatingFileHandler('app.log', maxBytes=10000, backupCount=1)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)

# Define route for the main page
@app.route('/')
def index():
    return render_template('input.html')

# Define route for form submission
@app.route('/submit', methods=['POST'])
def submit():
    return process_documents_from_form()

# Define route to show results
@app.route('/results')
def results():
    session_id = session.get("session_id", "")
    data = facts_storage.get(session_id, {"question": "No question found", "facts": ["No facts found"], "status": "processing"})
    results_url = url_for('results', _external=True, _scheme='https')
    return render_template('results.html', question=data['question'], facts=data['facts'], results_url=results_url)

# Define route for submitting questions and documents
@app.route('/submit_question_and_documents', methods=['POST'])
def submit_question_and_documents():
    data = request.json
    session_id = request.headers.get("Session-ID", "")
    session['session_id'] = session_id
    question = data.get('question')
    documents = data.get('documents')
    return process_documents(documents, question, session_id)

# Define route to get questions and facts
@app.route('/get_question_and_facts', methods=['GET'])
def get_question_and_facts():
    session_id = session.get("session_id", "")
    data = facts_storage.get(session_id, {"question": "No question found", "facts": None, "status": "processing"})
    response_model = GetQuestionAndFactsResponse(**data)
    return jsonify(response_model.dict()), 200

# Helper function to process documents from a form
def process_documents_from_form():
    question = request.form.get('question')
    call_logs_urls = request.form.getlist('call_logs[]')
    session_id = request.form.get('session_id', "")
    session['session_id'] = session_id
    return process_documents(call_logs_urls, question, session_id)

# Helper function to process documents and store facts
def process_documents(documents, question, session_id):
    # Initialize processing status
    facts_storage[session_id] = {"question": question, "facts": [], "status": "processing"}
    facts = []
    session['question'] = question
    session['facts'] = []
    session['status'] = 'processing'


    messages = [{"role": "system", "content": "You are a helpful assistant who focuses on processing a sequence of call logs and extracting facts"}]
    for index, log_url in enumerate(documents):
        try:
            # Attempt to fetch the document from the URL
            response = requests.get(log_url, timeout=10)
            response.raise_for_status()
            if 'text/plain' not in response.headers.get('Content-Type', ''):
                raise ValueError("Invalid content type")
        except (requests.RequestException, ValueError) as e:
            app.logger.error(f"Error fetching or processing {log_url}: {str(e)}")
            return jsonify({'success': False, 'error': f"URL number {index + 1} contents could not be accessed.", 'index': index + 1})
        app.logger.info(f"Text fetched from {log_url}: {response.text[:200]}")

        # Process documents and extract facts based on the request logic
        if index == 0:
            messages.append({"role": "user", "content": f"Answer this question = {question}, by extracting relevant and single-sentence facts from this call log = {response.text}. Your output should only be a bulleted list of concise, single-sentence facts. Do not provide reasons or context behind the facts. I just only want the facts based on the question and nothing else. You must extract at least 1 fact and at most 10 facts."})
        else:
            known_facts = ' '.join(facts)
            messages.append({"role": "user", "content": f"Answer this question = {question}, these are the known facts = {known_facts}. Generate a new bulleted list of concise, single-sentence facts from the call log = {response.text}. You can generate this new list by performing the following operations based on this call log : (1) changing or extending the known facts with new facts you extract from the call log (2) Adding new facts extracted from the call log to the known facts (3) Removing the known facts that are no longer true based on this call log.Your output should only be a bulleted list of concise, single-sentence facts. Do not provide reasons or context behind the facts. I just only want the facts based on the question and nothing else. You must extract at least 1 fact and at most 10 facts"})
        payload = {
            "model": "gpt-4",
            "messages": messages,
            "max_tokens": 100,
            "temperature": 0.1
        }
        headers = {
            "Authorization": f"Bearer {openai_api_key}"
        }
        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
        response_data = response.json()
        if 'choices' in response_data and response_data['choices']:
            last_choice = response_data['choices'][0]
            new_facts = last_choice['message']['content'] if last_choice['message']['role'] == 'assistant' else ""
            facts=new_facts.split('\n')
            
    # Update facts storage upon successful processing
    facts_storage[session_id] = {"question": question, "facts": facts, "status": "done"}
    if request.method == 'POST':
        return jsonify({'success': True, 'redirect_url': url_for('results', _external=True, _scheme='https')})
    return jsonify({}), 200




