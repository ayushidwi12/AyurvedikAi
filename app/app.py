from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
import sqlite3
import hashlib
import os
from werkzeug.utils import secure_filename
from transformers import pipeline
import google.generativeai as genai
import time
from PIL import Image
import io
import base64
import markdown

# Flask app initialization
app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Custom Jinja2 filter for markdown
@app.template_filter('markdown')
def markdown_filter(text):
    return markdown.markdown(text, extensions=['nl2br', 'fenced_code'])

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Load the image classification model
pipe = pipeline("image-classification", "dima806/medicinal_plants_image_detection")



api_key = ""



# Configure Gemini AI
genai.configure(api_key=api_key)

generation_config = {
    "temperature": 0.9,
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 8192,
}

safety_settings = [
    {
        "category": "HARM_CATEGORY_HARASSMENT",
        "threshold": "BLOCK_MEDIUM_AND_ABOVE"
    },
    {
        "category": "HARM_CATEGORY_HATE_SPEECH",
        "threshold": "BLOCK_MEDIUM_AND_ABOVE"
    },
    {
        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "threshold": "BLOCK_MEDIUM_AND_ABOVE"
    },
    {
        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
        "threshold": "BLOCK_MEDIUM_AND_ABOVE"
    },
]

# Initialize Gemini model
model_genai = genai.GenerativeModel(
    model_name="gemini-2.0-flash",
    generation_config=generation_config,
    safety_settings=safety_settings
)

# Database initialization
def init_db():
    conn = sqlite3.connect('users.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  email TEXT UNIQUE NOT NULL,
                  password TEXT NOT NULL)''')
    conn.commit()
    conn.close()

# Hash password
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Check if user is logged in
def is_logged_in():
    return 'user_id' in session

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if not username or not email or not password:
            flash('All fields are required!', 'error')
            return render_template('register.html')
        
        hashed_password = hash_password(password)
        
        try:
            conn = sqlite3.connect('users.db')
            c = conn.cursor()
            c.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                     (username, email, hashed_password))
            conn.commit()
            conn.close()
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('Username or email already exists!', 'error')
            return render_template('register.html')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if not username or not password:
            flash('All fields are required!', 'error')
            return render_template('login.html')
        
        hashed_password = hash_password(password)
        
        conn = sqlite3.connect('users.db')
        c = conn.cursor()
        c.execute("SELECT id, username FROM users WHERE username = ? AND password = ?",
                 (username, hashed_password))
        user = c.fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['username'] = user[1]
            flash(f'Welcome back, {user[1]}!', 'success')
            return redirect(url_for('predict'))
        else:
            flash('Invalid username or password!', 'error')
            return render_template('login.html')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/predict', methods=['GET', 'POST'])
def predict():
    if not is_logged_in():
        flash('Please login to access this page.', 'error')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file selected!', 'error')
            return render_template('predict.html')
        
        file = request.files['file']
        if file.filename == '':
            flash('No file selected!', 'error')
            return render_template('predict.html')
        
        if file and allowed_file(file.filename):
            try:
                # Process the image
                image = Image.open(file.stream)
                
                # Perform image classification
                outputs = pipe(image)
                plant_name = outputs[0]['label']
                confidence = outputs[0]['score']
                
                # Convert image to base64 for display
                img_buffer = io.BytesIO()
                image.save(img_buffer, format='PNG')
                img_str = base64.b64encode(img_buffer.getvalue()).decode()
                
                return render_template('predict.html', 
                                     prediction=plant_name, 
                                     confidence=confidence,
                                     image_data=img_str,
                                     show_result=True)
            except Exception as e:
                flash(f'Error processing image: {str(e)}', 'error')
                return render_template('predict.html')
        else:
            flash('Invalid file type! Please upload an image.', 'error')
            return render_template('predict.html')
    
    return render_template('predict.html')

@app.route('/plant_info/<plant_name>')
def plant_info(plant_name):
    if not is_logged_in():
        flash('Please login to access this page.', 'error')
        return redirect(url_for('login'))
    
    try:
        chat = model_genai.start_chat(history=[])
        chat.send_message("You are AyurVedik ML, an expert in medicinal plants and Ayurveda. Provide detailed, accurate information about medicinal plants including their benefits, uses, preparation methods, and precautions. Use emojis to make the response engaging. Format your response in clean HTML with proper tags like <h3>, <strong>, <ul>, <li>, <p> etc. Do not use markdown syntax like *, **, or #.")
        
        prompt = f"Tell me everything about the medicinal plant '{plant_name}'. Include its scientific name, medicinal properties, traditional uses, preparation methods, health benefits, precautions, and any interesting facts. Make the response comprehensive yet easy to understand with proper HTML formatting and emojis. Use HTML tags for formatting, not markdown."
        
        response = chat.send_message(prompt)
        time.sleep(0.5)
        
        return render_template('plant_info.html', 
                             plant_name=plant_name, 
                             plant_info=response.text)
    except Exception as e:
        flash(f'Error getting plant information: {str(e)}', 'error')
        return redirect(url_for('predict'))

@app.route('/chat_with_ml', methods=['POST'])
def chat_with_ml():
    if not is_logged_in():
        return jsonify({"error": "Please login first"}), 401
    
    try:
        user_message = request.json.get('message', '').lower()
        
        chat = model_genai.start_chat(history=[])
        chat.send_message("You are AyurVedik ML, an expert in medicinal plants and Ayurveda. Answer questions about medicinal plants, their uses, benefits, and Ayurvedic practices. Use emojis to make responses engaging. Format responses in clean HTML with proper tags. Do not use markdown syntax.")
        
        response = chat.send_message(user_message)
        time.sleep(0.5)
        
        return jsonify({"response": response.text})
    except Exception as e:
        print(f"Error in chat_with_ml: {str(e)}")
        return jsonify({"response": "I'm sorry, I encountered an error. Please try again later."}), 500

@app.route('/about')
def about():
    return render_template('about.html')

def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

if __name__ == "__main__":
    init_db()
    app.run(debug=True)

