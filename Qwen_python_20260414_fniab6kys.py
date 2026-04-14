import os
import secrets
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///school.db'
app.config['UPLOAD_FOLDER'] = 'subject_folders'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'jpg', 'png', 'zip'}

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- DATABASE MODELS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role = db.Column(db.String(20), default='teacher')  # admin, teacher, content_manager
    subject = db.Column(db.String(50))  # Хичээлийн нэр (багш нарт)
    access_code = db.Column(db.String(20))  # Хавтасны код
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class News(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(300))
    author = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_published = db.Column(db.Boolean, default=True)

class SchoolInfo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_count = db.Column(db.Integer, default=0)
    teacher_count = db.Column(db.Integer, default=0)
    phone = db.Column(db.String(50))
    email = db.Column(db.String(100))
    address = db.Column(db.String(200))
    motto = db.Column(db.String(300))
    description = db.Column(db.Text)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- ROUTES ---
@app.route('/')
def index():
    news = News.query.filter_by(is_published=True).order_by(News.created_at.desc()).limit(5).all()
    info = SchoolInfo.query.first()
    return render_template('index.html', news=news, info=info)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Нэр эсвэл нууц үг буруу байна.')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        users = User.query.all()
        return render_template('admin_dashboard.html', users=users)
    return render_template('teacher_dashboard.html', subject=current_user.subject, code=current_user.access_code)

# --- ADMIN ROUTES ---
@app.route('/admin/add_user', methods=['POST'])
@login_required
def add_user():
    if current_user.role != 'admin':
        flash('Хандах эрхгүй!')
        return redirect(url_for('dashboard'))
    
    username = request.form['username']
    password = generate_password_hash(request.form['password'])
    role = request.form['role']
    subject = request.form.get('subject', '')
    access_code = request.form.get('access_code', secrets.token_hex(4))
    
    # Хавтас автоматаар үүсгэх
    if subject:
        folder_path = os.path.join(app.config['UPLOAD_FOLDER'], subject.lower().replace(' ', '_'))
        os.makedirs(folder_path, exist_ok=True)
    
    new_user = User(username=username, email=f"{username}@most.edu.mn", 
                   password_hash=password, role=role, subject=subject, access_code=access_code)
    db.session.add(new_user)
    db.session.commit()
    flash(f'{username} амжилттай бүртгэгдлээ. Хавтасны код: {access_code}')
    return redirect(url_for('dashboard'))

@app.route('/admin/add_news', methods=['POST'])
@login_required
def add_news():
    if current_user.role not in ['admin', 'content_manager']:
        flash('Хандах эрхгүй!')
        return redirect(url_for('dashboard'))
    
    title = request.form['title']
    content = request.form['content']
    author = current_user.username
    news = News(title=title, content=content, author=author)
    db.session.add(news)
    db.session.commit()
    flash('Мэдээ амжилттай нэмэгдлээ!')
    return redirect(url_for('dashboard'))

@app.route('/admin/update_info', methods=['POST'])
@login_required
def update_info():
    if current_user.role != 'admin':
        flash('Хандах эрхгүй!')
        return redirect(url_for('dashboard'))
    
    info = SchoolInfo.query.first()
    if not info:
        info = SchoolInfo()
        db.session.add(info)
    
    info.student_count = int(request.form.get('student_count', 0))
    info.teacher_count = int(request.form.get('teacher_count', 0))
    info.phone = request.form.get('phone')
    info.email = request.form.get('email')
    info.address = request.form.get('address')
    info.motto = request.form.get('motto')
    info.description = request.form.get('description')
    db.session.commit()
    flash('Сургуулийн мэдээлэл шинэчлэгдлээ!')
    return redirect(url_for('dashboard'))

# --- TEACHER FILE ROUTES ---
@app.route('/teacher/files', methods=['GET', 'POST'])
@login_required
def teacher_files():
    if current_user.role != 'teacher' and current_user.role != 'admin':
        flash('Зөвхөн багш нар хандах боломжтой!')
        return redirect(url_for('dashboard'))
    
    subject_folder = current_user.subject.lower().replace(' ', '_')
    folder_path = os.path.join(app.config['UPLOAD_FOLDER'], subject_folder)
    os.makedirs(folder_path, exist_ok=True)
    
    if request.method == 'POST' and 'file' in request.files:
        file = request.files['file']
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
            file.save(os.path.join(folder_path, timestamp + filename))
            flash('Файл амжилттай байршуулагдлаа!')
    
    files = []
    if os.path.exists(folder_path):
        files = [{'name': f, 'size': round(os.path.getsize(os.path.join(folder_path, f))/1024, 1),
                 'date': datetime.fromtimestamp(os.path.getmtime(os.path.join(folder_path, f))).strftime('%Y-%m-%d %H:%M')}
                for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
        files.sort(key=lambda x: x['date'], reverse=True)
    
    return render_template('teacher_files.html', files=files, subject=current_user.subject, folder=subject_folder)

@app.route('/download/<subject>/<filename>')
@login_required
def download_file(subject, filename):
    if current_user.subject.lower().replace(' ', '_') == subject or current_user.role == 'admin':
        return send_from_directory(os.path.join(app.config['UPLOAD_FOLDER'], subject), filename, as_attachment=True)
    flash('Энэ хавтасанд хандах эрхгүй!')
    return redirect(url_for('teacher_files'))

# --- INIT DB ---
with app.app_context():
    db.create_all()
    # Default admin
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', email='admin@most.edu.mn',
                    password_hash=generate_password_hash('admin123'), role='admin')
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)