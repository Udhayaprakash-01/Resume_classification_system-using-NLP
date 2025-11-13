import os
import uuid
import json
import requests
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from utils import extract_text_from_file, get_embedding, cosine_similarity
from models import db, User, Vacancy

UPLOAD_FOLDER = 'uploads'
ALLOWED_EXT = {'pdf', 'docx', 'doc', 'txt'}

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'devsecret')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

db.init_app(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# Default Job Roles
JOB_ROLES_JSON = os.path.join(os.path.dirname(__file__), 'job_roles.json')
if os.path.exists(JOB_ROLES_JSON):
    with open(JOB_ROLES_JSON, 'r') as f:
        JOB_ROLES = json.load(f)
else:
    JOB_ROLES = [
        {"id": "data_scientist", "title": "Data Scientist", "desc": "Python, ML, pandas, scikit-learn, statistics"},
        {"id": "web_developer", "title": "Web Developer", "desc": "HTML, CSS, JavaScript, React, Node.js"},
        {"id": "marketing_executive", "title": "Marketing Executive", "desc": "SEO, content, social media, analytics"},
        {"id": "devops_engineer", "title": "DevOps Engineer", "desc": "AWS, Docker, Kubernetes, CI/CD"},
        {"id": "nlp_engineer", "title": "NLP Engineer", "desc": "Transformers, NLP, PyTorch, text processing"}
    ]


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.before_request
def create_tables_once():
    if not getattr(app, '_tables_created', False):
        with app.app_context():
            db.create_all()
            app._tables_created = True


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        user_type = request.form['user_type']

        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'danger')
            return redirect(url_for('signup'))

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            user_type=user_type
        )
        db.session.add(user)
        db.session.commit()
        flash('Account created successfully. Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash('Invalid credentials', 'danger')
            return redirect(url_for('login'))

        login_user(user)
        return redirect(url_for('dashboard'))

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.user_type == 'hr':
        vacancies = Vacancy.query.filter_by(company_id=current_user.id).all()
        return render_template('hr_dashboard.html', vacancies=vacancies)
    else:
        return render_template('candidate_dashboard.html')


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


@app.route('/upload_resume', methods=['GET', 'POST'])
@login_required
def upload_resume():
    if request.method == 'POST':
        if 'resume' not in request.files:
            flash('No file uploaded', 'danger')
            return redirect(request.url)

        f = request.files['resume']
        if f.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)

        if f and allowed_file(f.filename):
            filename = secure_filename(f.filename)
            uid = f"{uuid.uuid4().hex[:8]}_{filename}"
            path = os.path.join(app.config['UPLOAD_FOLDER'], uid)
            f.save(path)

            text = extract_text_from_file(path)
            emb = get_embedding(text)

            scores = []
            for role in JOB_ROLES:
                role_emb = get_embedding(role['desc'])
                sim = cosine_similarity(emb, role_emb)
                scores.append((role['title'], float(sim)))

            scores.sort(key=lambda x: x[1], reverse=True)
            return render_template('result.html', scores=scores[:5], resume_text=text)
        else:
            flash('Unsupported file type', 'danger')
            return redirect(request.url)

    return render_template('upload_resume.html')


@app.route('/chatbot')
@login_required
def chatbot():
    return render_template('chatbot.html')


@app.route('/extract_text', methods=['POST'])
@login_required
def extract_text():
    """Extract text from uploaded resume"""
    file = request.files.get('file')
    if not file:
        return jsonify({'text': ''})

    filename = secure_filename(file.filename)
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(path)

    text = extract_text_from_file(path)
    return jsonify({'text': text})


@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    """Handles chatbot messages and optional resume text"""
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'answer': '(Error) No valid JSON received.'})

        message = data.get('message', '').strip()
        resume_text = data.get('resume_text', '').strip()

        ollama_url = os.environ.get('OLLAMA_API_URL', 'http://localhost:11434')
        model = os.environ.get('OLLAMA_MODEL', 'llama3')

        prompt = f"""
        You are a helpful assistant. 
        Provide responses in clear, natural English — not JSON.

        User Question: {message}

        Resume Context (if provided):
        {resume_text[:2000]}
        """

        # Send request to Ollama and stream the output
        response = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=120
        )

        if response.status_code == 200:
            try:
                # Ollama returns JSON (possibly multiple lines)
                raw_text = response.text.strip()
                # Try to decode if possible
                try:
                    data = json.loads(raw_text)
                    text = data.get('response') or data.get('text') or ''
                except json.JSONDecodeError:
                    # If it’s not valid JSON, fallback to plain text
                    text = raw_text

                return jsonify({'answer': text})
            except Exception as e:
                return jsonify({'answer': f'(Parse Error) {str(e)}'})
        else:
            return jsonify({'answer': f"(Ollama Error {response.status_code}) {response.text}"})

    except requests.exceptions.ConnectionError:
        return jsonify({'answer': "(Ollama not reachable) Please ensure Ollama is running using `ollama serve`."})
    except Exception as e:
        return jsonify({'answer': f"(Unexpected error) {str(e)}"})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
