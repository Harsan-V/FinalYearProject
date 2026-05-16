from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime
from functools import wraps
import os
import json
from groq import Groq
from dotenv import load_dotenv
load_dotenv()
print("KEY VALUE:", os.getenv("GROQ_API_KEY"))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///legal_assistant.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Email Configuration
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
app.config['MAIL_USE_SSL'] = os.getenv('MAIL_USE_SSL', 'False').lower() == 'true'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME', 'developer.abn000@gmail.com')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD', 'wece jntw dwvt qojx')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'developer.abn000@gmail.com')

db = SQLAlchemy(app)
mail = Mail(app)

# Groq API client
GROQ_API_KEY = os.getenv('GROQ_API_KEY', 'your-groq-api-key-here')
groq_client = Groq(api_key=GROQ_API_KEY)

# Custom Jinja2 filters
@app.template_filter('rating_color')
def rating_color(rating):
    """Return color based on rating value"""
    if rating == 0:
        return '#9ca3af'  # Gray for no rating
    elif rating < 2:
        return '#ef4444'  # Red for poor
    elif rating < 3:
        return '#f59e0b'  # Orange for fair
    elif rating < 4:
        return '#eab308'  # Yellow for good
    else:
        return '#10b981'  # Green for excellent

@app.template_filter('rating_text')
def rating_text(rating):
    """Return text description of rating"""
    if rating == 0:
        return 'No reviews yet'
    elif rating < 2:
        return 'Poor'
    elif rating < 3:
        return 'Fair'
    elif rating < 4:
        return 'Good'
    elif rating < 4.5:
        return 'Very Good'
    else:
        return 'Excellent'

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    appointments = db.relationship('Appointment', backref='user', lazy=True)
    chat_messages = db.relationship('ChatMessage', backref='user', lazy=True)
    lawyer_chats = db.relationship('LawyerChat', foreign_keys='LawyerChat.user_id', backref='client', lazy=True)

class Lawyer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    charge_per_hour = db.Column(db.Float, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    experience = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=True)
    image = db.Column(db.String(200), default='default_lawyer.png')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    appointments = db.relationship('Appointment', backref='lawyer', lazy=True)
    lawyer_chats = db.relationship('LawyerChat', foreign_keys='LawyerChat.lawyer_id', backref='attorney', lazy=True)
    ratings = db.relationship('LawyerRating', backref='lawyer', lazy=True)
    
    @property
    def rating(self):
        if not self.ratings:
            return 0.0
        total = sum(r.rating for r in self.ratings)
        return round(total / len(self.ratings), 1)
    
    @property
    def rating_count(self):
        return len(self.ratings)

class LawyerRating(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lawyer_id = db.Column(db.Integer, db.ForeignKey('lawyer.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    review = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='ratings_given', lazy=True)
    appointment = db.relationship('Appointment', backref='rating', lazy=True)

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lawyer_id = db.Column(db.Integer, db.ForeignKey('lawyer.id'), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    response = db.Column(db.Text, nullable=False)
    problem_class = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class LawyerChat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    lawyer_id = db.Column(db.Integer, db.ForeignKey('lawyer.id'), nullable=False)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), nullable=False)
    sender_type = db.Column(db.String(10), nullable=False)  # 'user' or 'lawyer'
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ChatAttachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('lawyer_chat.id'), nullable=False)
    filename = db.Column(db.String(200), nullable=False)
    original_filename = db.Column(db.String(200), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)  # 'image' or 'document'
    file_size = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    chat = db.relationship('LawyerChat', backref='attachments', lazy=True)

# Create tables
with app.app_context():
    db.create_all()

# Decorators
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def lawyer_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'lawyer_id' not in session:
            flash('Please login as a lawyer to access this page.', 'error')
            return redirect(url_for('lawyer_login'))
        return f(*args, **kwargs)
    return decorated_function

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in {'png', 'jpg', 'jpeg', 'gif'}

def allowed_attachment(filename):
    ALLOWED_EXTENSIONS = {
        'png', 'jpg', 'jpeg', 'gif', 'webp',  # Images
        'pdf', 'doc', 'docx', 'txt', 'rtf',   # Documents
        'xls', 'xlsx', 'csv',                  # Spreadsheets
        'zip', 'rar'                           # Archives
    }
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_file_type(filename):
    image_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    return 'image' if ext in image_extensions else 'document'

def send_email(to, subject, template, **kwargs):
    """Send email using Flask-Mail"""
    try:
        msg = Message(
            subject=subject,
            recipients=[to],
            sender=app.config['MAIL_DEFAULT_SENDER']
        )
        msg.html = render_template(f'emails/{template}', **kwargs)
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Email sending failed: {str(e)}")
        return False

def send_appointment_accepted_email(user_email, lawyer_name, appointment):
    """Send email when lawyer accepts appointment"""
    subject = f"Appointment Accepted - {lawyer_name}"
    return send_email(
        to=user_email,
        subject=subject,
        template='appointment_accepted.html',
        lawyer_name=lawyer_name,
        appointment=appointment
    )

def send_appointment_rejected_email(user_email, lawyer_name, appointment):
    """Send email when lawyer rejects appointment"""
    subject = f"Appointment Update - {lawyer_name}"
    return send_email(
        to=user_email,
        subject=subject,
        template='appointment_rejected.html',
        lawyer_name=lawyer_name,
        appointment=appointment
    )

def send_new_appointment_email(lawyer_email, user_name, appointment):
    """Send email to lawyer when new appointment is received"""
    subject = f"New Appointment Request from {user_name}"
    return send_email(
        to=lawyer_email,
        subject=subject,
        template='new_appointment.html',
        user_name=user_name,
        appointment=appointment
    )

def classify_problem(conversation_history):
    """Classify the legal problem based on conversation"""
    categories = ['criminal', 'family', 'property', 'corporate', 'civil', 'labor', 'tax']
    
    prompt = f"""Based on this conversation about a legal issue, classify it into one of these categories: {', '.join(categories)}.

Conversation:
{conversation_history}

Respond with only the category name, nothing else."""
    
    try:
        response = groq_client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="openai/gpt-oss-120b",
            temperature=0.3,
            max_tokens=10
        )
        category = response.choices[0].message.content.strip().lower()
        return category if category in categories else 'civil'
    except:
        return 'civil'

def get_ai_response(user_message, conversation_history):
    """Get AI response from Groq"""
    system_prompt = """You are an expert legal assistant AI. Your role is to:
1. Ask clarifying questions to understand the user's legal problem thoroughly
2. Once you have enough information, provide:
   - Relevant legal sections and laws (IPC sections if applicable)
   - Possible legal remedies
   - Steps to resolve the issue
   - General legal advice

Ask one question at a time to understand the situation better. Be professional, empathetic, and thorough.
When you have enough information, provide comprehensive legal guidance."""

    messages = [{"role": "system", "content": system_prompt}]
    
    # Add conversation history
    for msg in conversation_history:
        messages.append({"role": "user", "content": msg['message']})
        messages.append({"role": "assistant", "content": msg['response']})
    
    # Add current message
    messages.append({"role": "user", "content": user_message})
    
    try:
        response = groq_client.chat.completions.create(
            messages=messages,
            model="openai/gpt-oss-120b",
            temperature=0.7,
            max_tokens=1024
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"I apologize, but I'm having trouble processing your request. Please try again. Error: {str(e)}"

# Routes - Home
@app.route('/')
def index():
    return render_template('index.html')

# User Authentication
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'error')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('register'))
        
        hashed_password = generate_password_hash(password)
        new_user = User(username=username, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

# User Dashboard
@app.route('/dashboard')
@login_required
def dashboard():
    user = User.query.get(session['user_id'])
    appointments = Appointment.query.filter_by(user_id=user.id).order_by(Appointment.created_at.desc()).all()
    return render_template('dashboard.html', user=user, appointments=appointments)

# Chat with AI Assistant
@app.route('/chat')
@login_required
def chat():
    return render_template('chat.html')

@app.route('/api/chat', methods=['POST'])
@login_required
def api_chat():
    data = request.get_json()
    user_message = data.get('message', '')
    
    # Get conversation history
    user_id = session['user_id']
    history = ChatMessage.query.filter_by(user_id=user_id).order_by(ChatMessage.created_at).all()
    conversation_history = [{'message': msg.message, 'response': msg.response} for msg in history]
    
    # Get AI response
    ai_response = get_ai_response(user_message, conversation_history)
    
    # Check if problem is identified (simple heuristic)
    problem_class = None
    if len(conversation_history) >= 3 or 'sections' in ai_response.lower() or 'ipc' in ai_response.lower():
        conv_text = '\n'.join([f"User: {h['message']}\nAssistant: {h['response']}" for h in conversation_history])
        conv_text += f"\nUser: {user_message}\nAssistant: {ai_response}"
        problem_class = classify_problem(conv_text)
    
    # Save to database
    chat_msg = ChatMessage(
        user_id=user_id,
        message=user_message,
        response=ai_response,
        problem_class=problem_class
    )
    db.session.add(chat_msg)
    db.session.commit()
    
    # Get suggested lawyers if problem is classified
    suggested_lawyers = []
    if problem_class:
        lawyers = Lawyer.query.filter_by(category=problem_class).all()
        # Sort by rating in Python (since rating is now a property)
        lawyers = sorted(lawyers, key=lambda x: x.rating, reverse=True)[:3]
        suggested_lawyers = [{
            'id': lawyer.id,
            'name': lawyer.name,
            'category': lawyer.category,
            'experience': lawyer.experience,
            'rating': lawyer.rating,
            'charge_per_hour': lawyer.charge_per_hour,
            'location': lawyer.location
        } for lawyer in lawyers]
    
    return jsonify({
        'response': ai_response,
        'problem_class': problem_class,
        'suggested_lawyers': suggested_lawyers
    })

@app.route('/api/chat/history', methods=['GET'])
@login_required
def chat_history():
    user_id = session['user_id']
    history = ChatMessage.query.filter_by(user_id=user_id).order_by(ChatMessage.created_at).all()
    
    return jsonify([{
        'message': msg.message,
        'response': msg.response,
        'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
    } for msg in history])

# Lawyers List
@app.route('/lawyers')
def lawyers():
    category = request.args.get('category', '')
    search = request.args.get('search', '')
    sort = request.args.get('sort', 'rating')
    
    query = Lawyer.query
    
    if category:
        query = query.filter_by(category=category)
    
    if search:
        query = query.filter(
            db.or_(
                Lawyer.name.ilike(f'%{search}%'),
                Lawyer.location.ilike(f'%{search}%'),
                Lawyer.description.ilike(f'%{search}%')
            )
        )
    
    # Get all lawyers first (we'll sort in Python for rating)
    lawyers_list = query.all()
    
    # Sort based on selected option
    if sort == 'rating':
        lawyers_list = sorted(lawyers_list, key=lambda x: x.rating, reverse=True)
    elif sort == 'experience':
        lawyers_list = sorted(lawyers_list, key=lambda x: x.experience, reverse=True)
    elif sort == 'price_low':
        lawyers_list = sorted(lawyers_list, key=lambda x: x.charge_per_hour)
    elif sort == 'price_high':
        lawyers_list = sorted(lawyers_list, key=lambda x: x.charge_per_hour, reverse=True)
    
    categories = ['criminal', 'family', 'property', 'corporate', 'civil', 'labor', 'tax']
    
    return render_template('lawyers.html', lawyers=lawyers_list, categories=categories, selected_category=category)

@app.route('/lawyer/<int:lawyer_id>')
def lawyer_profile(lawyer_id):
    lawyer = Lawyer.query.get_or_404(lawyer_id)
    return render_template('lawyer_profile.html', lawyer=lawyer)

# Appointment
@app.route('/appointment/<int:lawyer_id>', methods=['POST'])
@login_required
def book_appointment(lawyer_id):
    description = request.form.get('description')
    
    appointment = Appointment(
        user_id=session['user_id'],
        lawyer_id=lawyer_id,
        description=description,
        status='pending'
    )
    db.session.add(appointment)
    db.session.commit()
    
    # Send email notification to lawyer
    user = User.query.get(session['user_id'])
    lawyer = Lawyer.query.get(lawyer_id)
    send_new_appointment_email(lawyer.email, user.username, appointment)
    
    flash('Appointment request sent successfully! The lawyer will be notified via email.', 'success')
    return redirect(url_for('dashboard'))

# Lawyer Authentication
@app.route('/lawyer/register', methods=['GET', 'POST'])
def lawyer_register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        category = request.form.get('category')
        phone = request.form.get('phone')
        charge_per_hour = float(request.form.get('charge_per_hour'))
        location = request.form.get('location')
        experience = int(request.form.get('experience'))
        description = request.form.get('description')
        
        if Lawyer.query.filter_by(email=email).first():
            flash('Email already registered.', 'error')
            return redirect(url_for('lawyer_register'))
        
        # Handle image upload
        image_filename = 'default_lawyer.png'
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                image_filename = f"{timestamp}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        
        hashed_password = generate_password_hash(password)
        new_lawyer = Lawyer(
            name=name,
            email=email,
            password=hashed_password,
            category=category,
            phone=phone,
            charge_per_hour=charge_per_hour,
            location=location,
            experience=experience,
            description=description,
            image=image_filename
        )
        db.session.add(new_lawyer)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('lawyer_login'))
    
    categories = ['criminal', 'family', 'property', 'corporate', 'civil', 'labor', 'tax']
    return render_template('lawyer_register.html', categories=categories)

@app.route('/lawyer/login', methods=['GET', 'POST'])
def lawyer_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        lawyer = Lawyer.query.filter_by(email=email).first()
        
        if lawyer and check_password_hash(lawyer.password, password):
            session['lawyer_id'] = lawyer.id
            session['lawyer_name'] = lawyer.name
            flash('Login successful!', 'success')
            return redirect(url_for('lawyer_dashboard'))
        else:
            flash('Invalid email or password.', 'error')
    
    return render_template('lawyer_login.html')

@app.route('/lawyer/logout')
def lawyer_logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))

# Lawyer Dashboard
@app.route('/lawyer/dashboard')
@lawyer_login_required
def lawyer_dashboard():
    lawyer = Lawyer.query.get(session['lawyer_id'])
    pending_appointments = Appointment.query.filter_by(lawyer_id=lawyer.id, status='pending').order_by(Appointment.created_at.desc()).all()
    accepted_appointments = Appointment.query.filter_by(lawyer_id=lawyer.id, status='accepted').order_by(Appointment.updated_at.desc()).all()
    rejected_appointments = Appointment.query.filter_by(lawyer_id=lawyer.id, status='rejected').order_by(Appointment.updated_at.desc()).all()
    
    return render_template('lawyer_dashboard.html', 
                         lawyer=lawyer,
                         pending_appointments=pending_appointments,
                         accepted_appointments=accepted_appointments,
                         rejected_appointments=rejected_appointments)

@app.route('/lawyer/appointment/<int:appointment_id>/accept', methods=['POST'])
@lawyer_login_required
def accept_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    
    if appointment.lawyer_id != session['lawyer_id']:
        flash('Unauthorized action.', 'error')
        return redirect(url_for('lawyer_dashboard'))
    
    appointment.status = 'accepted'
    appointment.updated_at = datetime.utcnow()
    db.session.commit()
    
    # Send email notification to user
    user = User.query.get(appointment.user_id)
    lawyer = Lawyer.query.get(session['lawyer_id'])
    send_appointment_accepted_email(user.email, lawyer.name, appointment)
    
    flash('Appointment accepted! The client has been notified via email.', 'success')
    return redirect(url_for('lawyer_dashboard'))

@app.route('/lawyer/appointment/<int:appointment_id>/reject', methods=['POST'])
@lawyer_login_required
def reject_appointment(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    
    if appointment.lawyer_id != session['lawyer_id']:
        flash('Unauthorized action.', 'error')
        return redirect(url_for('lawyer_dashboard'))
    
    appointment.status = 'rejected'
    appointment.updated_at = datetime.utcnow()
    db.session.commit()
    
    # Send email notification to user
    user = User.query.get(appointment.user_id)
    lawyer = Lawyer.query.get(session['lawyer_id'])
    send_appointment_rejected_email(user.email, lawyer.name, appointment)
    
    flash('Appointment rejected. The client has been notified via email.', 'success')
    return redirect(url_for('lawyer_dashboard'))

# 1-to-1 Chat between User and Lawyer
@app.route('/chat/lawyer/<int:appointment_id>')
@login_required
def user_lawyer_chat(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    
    if appointment.user_id != session['user_id']:
        flash('Unauthorized access.', 'error')
        return redirect(url_for('dashboard'))
    
    if appointment.status != 'accepted':
        flash('Chat is only available for accepted appointments.', 'error')
        return redirect(url_for('dashboard'))
    
    lawyer = Lawyer.query.get(appointment.lawyer_id)
    return render_template('user_lawyer_chat.html', appointment=appointment, lawyer=lawyer)

@app.route('/lawyer/chat/<int:appointment_id>')
@lawyer_login_required
def lawyer_user_chat(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    
    if appointment.lawyer_id != session['lawyer_id']:
        flash('Unauthorized access.', 'error')
        return redirect(url_for('lawyer_dashboard'))
    
    if appointment.status != 'accepted':
        flash('Chat is only available for accepted appointments.', 'error')
        return redirect(url_for('lawyer_dashboard'))
    
    user = User.query.get(appointment.user_id)
    return render_template('lawyer_user_chat.html', appointment=appointment, user=user)

@app.route('/api/lawyer-chat/<int:appointment_id>/messages', methods=['GET'])
def get_lawyer_chat_messages(appointment_id):
    if 'user_id' not in session and 'lawyer_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    appointment = Appointment.query.get_or_404(appointment_id)
    
    # Check authorization
    if 'user_id' in session and appointment.user_id != session['user_id']:
        return jsonify({'error': 'Unauthorized'}), 401
    if 'lawyer_id' in session and appointment.lawyer_id != session['lawyer_id']:
        return jsonify({'error': 'Unauthorized'}), 401
    
    messages = LawyerChat.query.filter_by(appointment_id=appointment_id).order_by(LawyerChat.created_at).all()
    
    result = []
    for msg in messages:
        attachments = ChatAttachment.query.filter_by(chat_id=msg.id).all()
        result.append({
            'id': msg.id,
            'sender_type': msg.sender_type,
            'message': msg.message,
            'created_at': msg.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'attachments': [{
                'id': att.id,
                'filename': att.filename,
                'original_filename': att.original_filename,
                'file_type': att.file_type,
                'file_size': att.file_size
            } for att in attachments]
        })
    
    return jsonify(result)

@app.route('/api/lawyer-chat/<int:appointment_id>/send', methods=['POST'])
def send_lawyer_chat_message(appointment_id):
    if 'user_id' not in session and 'lawyer_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    appointment = Appointment.query.get_or_404(appointment_id)
    
    # Get message from either JSON or form data
    if request.is_json:
        message_text = request.json.get('message', '')
    else:
        message_text = request.form.get('message', '')
    
    # Determine sender type and check authorization
    if 'user_id' in session:
        if appointment.user_id != session['user_id']:
            return jsonify({'error': 'Unauthorized'}), 401
        sender_type = 'user'
        user_id = session['user_id']
        lawyer_id = appointment.lawyer_id
    else:
        if appointment.lawyer_id != session['lawyer_id']:
            return jsonify({'error': 'Unauthorized'}), 401
        sender_type = 'lawyer'
        user_id = appointment.user_id
        lawyer_id = session['lawyer_id']
    
    new_message = LawyerChat(
        user_id=user_id,
        lawyer_id=lawyer_id,
        appointment_id=appointment_id,
        sender_type=sender_type,
        message=message_text
    )
    db.session.add(new_message)
    db.session.flush()  # Get the message ID
    
    # Handle file attachments
    attachments_data = []
    if 'files[]' in request.files:
        files = request.files.getlist('files[]')
        for file in files:
            if file and allowed_attachment(file.filename):
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
                unique_filename = f"{timestamp}_{filename}"
                
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(file_path)
                
                # Get file size
                file_size = os.path.getsize(file_path)
                file_type = get_file_type(filename)
                
                attachment = ChatAttachment(
                    chat_id=new_message.id,
                    filename=unique_filename,
                    original_filename=filename,
                    file_type=file_type,
                    file_size=file_size
                )
                db.session.add(attachment)
                
                attachments_data.append({
                    'filename': unique_filename,
                    'original_filename': filename,
                    'file_type': file_type,
                    'file_size': file_size
                })
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'message': {
            'id': new_message.id,
            'sender_type': sender_type,
            'message': message_text,
            'created_at': new_message.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'attachments': attachments_data
        }
    })

@app.route('/api/download/<filename>')
def download_file(filename):
    if 'user_id' not in session and 'lawyer_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    # Verify the file belongs to an appointment the user has access to
    attachment = ChatAttachment.query.filter_by(filename=filename).first_or_404()
    chat = LawyerChat.query.get(attachment.chat_id)
    
    # Check authorization
    if 'user_id' in session and chat.user_id != session['user_id']:
        return jsonify({'error': 'Unauthorized'}), 401
    if 'lawyer_id' in session and chat.lawyer_id != session['lawyer_id']:
        return jsonify({'error': 'Unauthorized'}), 401
    
    from flask import send_from_directory
    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        filename,
        as_attachment=True,
        download_name=attachment.original_filename
    )

# Rating Routes
@app.route('/rate-lawyer/<int:appointment_id>', methods=['GET', 'POST'])
@login_required
def rate_lawyer(appointment_id):
    appointment = Appointment.query.get_or_404(appointment_id)
    
    # Check if user owns this appointment
    if appointment.user_id != session['user_id']:
        flash('Unauthorized access.', 'error')
        return redirect(url_for('dashboard'))
    
    # Check if appointment is accepted
    if appointment.status != 'accepted':
        flash('You can only rate accepted appointments.', 'error')
        return redirect(url_for('dashboard'))
    
    # Check if already rated
    existing_rating = LawyerRating.query.filter_by(
        appointment_id=appointment_id,
        user_id=session['user_id']
    ).first()
    
    if request.method == 'POST':
        rating_value = int(request.form.get('rating'))
        review_text = request.form.get('review', '')
        
        if rating_value < 1 or rating_value > 5:
            flash('Rating must be between 1 and 5 stars.', 'error')
            return redirect(url_for('rate_lawyer', appointment_id=appointment_id))
        
        if existing_rating:
            # Update existing rating
            existing_rating.rating = rating_value
            existing_rating.review = review_text
            existing_rating.created_at = datetime.utcnow()
        else:
            # Create new rating
            new_rating = LawyerRating(
                lawyer_id=appointment.lawyer_id,
                user_id=session['user_id'],
                appointment_id=appointment_id,
                rating=rating_value,
                review=review_text
            )
            db.session.add(new_rating)
        
        db.session.commit()
        flash('Rating submitted successfully!', 'success')
        return redirect(url_for('dashboard'))
    
    lawyer = Lawyer.query.get(appointment.lawyer_id)
    return render_template('rate_lawyer.html', 
                         appointment=appointment, 
                         lawyer=lawyer,
                         existing_rating=existing_rating)

@app.route('/lawyer/<int:lawyer_id>/reviews')
def lawyer_reviews(lawyer_id):
    lawyer = Lawyer.query.get_or_404(lawyer_id)
    reviews = LawyerRating.query.filter_by(lawyer_id=lawyer_id).order_by(LawyerRating.created_at.desc()).all()
    return render_template('lawyer_reviews.html', lawyer=lawyer, reviews=reviews)

# About and Contact
@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

if __name__ == '__main__':
    # Create upload folder if it doesn't exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    app.run(debug=True)