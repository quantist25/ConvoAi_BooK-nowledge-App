from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, send_file, send_from_directory, jsonify
from werkzeug.utils import secure_filename
import os
import logging
import io
from google.cloud import speech
import google.cloud.language_v1 as language_v1
import google.cloud.texttospeech as tts
import PyPDF2
import re

app = Flask(__name__)

# Configure upload folders
UPLOAD_FOLDER = 'uploads'
BOOK_FOLDER = 'books'
ALLOWED_EXTENSIONS = {'wav', 'txt', 'pdf'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['BOOK_FOLDER'] = BOOK_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max upload size

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(BOOK_FOLDER, exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Google Cloud Clients
try:
    speech_client = speech.SpeechClient()
    language_client = language_v1.LanguageServiceClient()
    tts_client = tts.TextToSpeechClient()
    logger.info("Google Cloud clients initialized successfully")
except Exception as e:
    logger.error(f"Error initializing Google Cloud clients: {e}")

# Global variable to track the current book
current_book = {
    "filename": None,
    "title": None,
    "content": None,
    "chunks": None
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_files():
    audio_files = []
    book_files = []
    try:
        # Get audio files
        for filename in os.listdir(UPLOAD_FOLDER):
            if filename.endswith('.wav'):
                audio_files.append(filename)
        audio_files.sort(reverse=True)
        
        # Get book files
        for filename in os.listdir(BOOK_FOLDER):
            if filename.endswith('.pdf'):
                book_files.append(filename)
        book_files.sort()
    except Exception as e:
        logger.error(f"Error listing files: {e}")
    
    return audio_files, book_files

def extract_text_from_pdf(pdf_path):
    """Extract text from a PDF file"""
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            
            # Clean up the text
            text = re.sub(r'\s+', ' ', text)  # Replace multiple spaces with a single space
            text = text.strip()
            
            return text
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        return ""

def chunk_text(text, chunk_size=4000, overlap=200):
    """Split text into chunks with overlap for context preservation"""
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        end = min(start + chunk_size, text_length)
        # If we're not at the end of the text, try to find a good break point
        if end < text_length:
            # Find the last period, question mark, or exclamation point followed by a space
            last_break = max(
                text.rfind('. ', start, end),
                text.rfind('? ', start, end),
                text.rfind('! ', start, end)
            )
            
            if last_break != -1:
                end = last_break + 1  # Include the period
        
        chunk = text[start:end].strip()
        if chunk:  # Only add non-empty chunks
            chunks.append(chunk)
        
        # Move start position, considering overlap
        start = end - overlap if end < text_length else text_length
    
    return chunks

def process_audio_to_text(audio_content):
    """Convert audio to text using Speech-to-Text"""
    try:
        audio = speech.RecognitionAudio(content=audio_content)
        config = speech.RecognitionConfig(
            language_code="en-US",
            enable_automatic_punctuation=True
        )
        
        response = speech_client.recognize(config=config, audio=audio)
        transcript = "\n".join([result.alternatives[0].transcript for result in response.results])
        
        return transcript
    except Exception as e:
        logger.error(f"Error in speech-to-text processing: {e}")
        return ""

def search_book_for_answer(question, book_chunks):
    """
    Find the most relevant chunks for answering the question
    and generate a response using Language API
    """
    try:
        # Simple keyword-based search to find relevant chunks
        # In a production app, you'd use embeddings for better semantic search
        question_words = set(re.findall(r'\b\w+\b', question.lower()))
        chunk_scores = []
        
        for i, chunk in enumerate(book_chunks):
            chunk_lower = chunk.lower()
            score = 0
            for word in question_words:
                if len(word) > 3:  # Only consider words longer than 3 chars
                    score += chunk_lower.count(word)
            chunk_scores.append((i, score))
        
        # Sort chunks by relevance score
        chunk_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Take the top 3 most relevant chunks
        top_chunks = [book_chunks[idx] for idx, score in chunk_scores[:3] if score > 0]
        
        if not top_chunks:
            # If no relevant chunks found, take the first chunk as fallback
            top_chunks = [book_chunks[0]]
        
        # Combine chunks and format prompt
        context = "\n\n".join(top_chunks)
        
        # Format a prompt for the Language API
        prompt = f"""
        Based on the following excerpt from the book:
        
        {context}
        
        Question: {question}
        
        Please provide a concise answer:
        """
        
        # Use Language API for natural language understanding
        document = language_v1.Document(
            content=prompt, 
            type_=language_v1.Document.Type.PLAIN_TEXT
        )
        
        # Analyze entities as a way to extract information
        # (This is a workaround since Language API isn't a chatbot API)
        entities = language_client.analyze_entities(request={'document': document}).entities
        
        # Extract the most salient information
        key_phrases = []
        for entity in entities:
            if entity.salience > 0.01:  # Only consider salient entities
                key_phrases.append(entity.name)
        
        # Generate a simple response based on entities
        # In a production app, you'd use a proper LLM API here
        if key_phrases:
            response = f"Based on the book, I found information about {', '.join(key_phrases[:5])}. "
            response += f"The book mentions these concepts in relation to your question about {question}."
        else:
            response = f"I couldn't find specific information about '{question}' in the book."
        
        return response
    except Exception as e:
        logger.error(f"Error searching book for answer: {e}")
        return f"I'm sorry, I couldn't process your question due to an error: {str(e)}"

def text_to_speech(text):
    """Convert text to speech using Google TTS"""
    try:
        synthesis_input = tts.SynthesisInput(text=text)
        
        voice = tts.VoiceSelectionParams(
            language_code="en-US",
            ssml_gender=tts.SsmlVoiceGender.NEUTRAL
        )
        
        audio_config = tts.AudioConfig(
            audio_encoding=tts.AudioEncoding.MP3
        )
        
        response = tts_client.synthesize_speech(
            input=synthesis_input,
            voice=voice,
            audio_config=audio_config
        )
        
        return response.audio_content
    except Exception as e:
        logger.error(f"Error in text-to-speech processing: {e}")
        return None

@app.route('/')
def index():
    audio_files, book_files = get_files()
    
    # Get transcript data for audio files
    transcripts = {}
    for audio_file in audio_files:
        text_file = audio_file.replace('.wav', '.txt')
        text_path = os.path.join(app.config['UPLOAD_FOLDER'], text_file)
        if os.path.exists(text_path):
            try:
                with open(text_path, 'r') as f:
                    transcripts[audio_file] = f.read()
            except Exception as e:
                logger.error(f"Error reading transcript file {text_file}: {e}")
    
    return render_template('index.html', 
                          audio_files=audio_files,
                          book_files=book_files,
                          transcripts=transcripts,
                          current_book=current_book)

@app.route('/upload-book', methods=['POST'])
def upload_book():
    if 'book_file' not in request.files:
        logger.warning("No book_file in request")
        return redirect(url_for('index'))
    
    file = request.files['book_file']
    
    if file.filename == '':
        logger.warning("Empty filename")
        return redirect(url_for('index'))
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['BOOK_FOLDER'], filename)
        
        try:
            file.save(filepath)
            logger.info(f"Book file saved as {filename}")
            
            # Process the PDF
            text = extract_text_from_pdf(filepath)
            chunks = chunk_text(text)
            
            # Update current book
            global current_book
            current_book = {
                "filename": filename,
                "title": filename.replace('.pdf', ''),
                "content": text[:1000] + "...",  # Store a preview
                "chunks": chunks
            }
            
            logger.info(f"Book processed: {len(chunks)} chunks created")
            
        except Exception as e:
            logger.error(f"Error saving book file: {e}")
    
    return redirect(url_for('index'))

@app.route('/set-current-book/<filename>')
def set_current_book(filename):
    filepath = os.path.join(app.config['BOOK_FOLDER'], filename)
    
    if os.path.exists(filepath):
        # Process the PDF
        text = extract_text_from_pdf(filepath)
        chunks = chunk_text(text)
        
        # Update current book
        global current_book
        current_book = {
            "filename": filename,
            "title": filename.replace('.pdf', ''),
            "content": text[:1000] + "...",  # Store a preview
            "chunks": chunks
        }
        
        logger.info(f"Current book set to: {filename}")
    
    return redirect(url_for('index'))

@app.route('/upload-question', methods=['POST'])
def upload_question():
    if 'audio_data' not in request.files:
        logger.warning("No audio_data in request")
        return redirect(url_for('index'))
    
    file = request.files['audio_data']
    
    if file.filename == '':
        logger.warning("Empty filename")
        return redirect(url_for('index'))
    
    if file and allowed_file(file.filename):
        # Check if a book is loaded
        global current_book
        if not current_book["chunks"]:
            logger.warning("No book loaded")
            return jsonify({"error": "Please load a book first"}), 400
        
        # Generate a timestamp-based filename
        filename = datetime.now().strftime("%Y%m%d-%H%M%S") + '.wav'
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        try:
            file.save(filepath)
            logger.info(f"Audio file saved as {filename}")
            
            # Process the audio question
            try:
                with open(filepath, 'rb') as audio_file:
                    content = audio_file.read()
                
                # Convert speech to text
                question = process_audio_to_text(content)
                
                if not question:
                    logger.warning("Could not transcribe question")
                    return jsonify({"error": "Could not understand the question"}), 400
                
                # Search the book for an answer
                answer = search_book_for_answer(question, current_book["chunks"])
                
                # Convert answer to speech
                audio_response = text_to_speech(answer)
                
                # Save the answer
                text_filename = filename.replace('.wav', '.txt')
                text_filepath = os.path.join(app.config['UPLOAD_FOLDER'], text_filename)
                
                with open(text_filepath, 'w') as text_file:
                    text_file.write(f"Question:\n{question}\n\n")
                    text_file.write(f"Answer:\n{answer}\n")
                
                # Save the audio response
                response_filename = filename.replace('.wav', '-response.mp3')
                response_filepath = os.path.join(app.config['UPLOAD_FOLDER'], response_filename)
                
                if audio_response:
                    with open(response_filepath, 'wb') as response_file:
                        response_file.write(audio_response)
                
                logger.info(f"Question processed and answer generated: {text_filename}")
                
                return jsonify({
                    "success": True,
                    "question": question,
                    "answer": answer,
                    "audio_url": url_for('uploaded_file', filename=response_filename)
                })
                
            except Exception as e:
                logger.error(f"Error processing question: {e}")
                return jsonify({"error": f"Error processing question: {str(e)}"}), 500
        
        except Exception as e:
            logger.error(f"Error saving audio file: {e}")
            return jsonify({"error": f"Error saving audio file: {str(e)}"}), 500
    
    return redirect(url_for('index'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/books/<filename>')
def book_file(filename):
    return send_from_directory(app.config['BOOK_FOLDER'], filename)

@app.route('/script.js', methods=['GET'])
def scripts_js():
    return send_file('./script.js')

@app.errorhandler(500)
def server_error(e):
    logger.error(f"Server error: {e}")
    return "Internal Server Error", 500

if __name__ == '__main__':
    app.run(debug=True)