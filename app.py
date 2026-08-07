import os
import sqlite3
import base64
import cv2
import numpy as np
from datetime import datetime
from io import BytesIO

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

from database import init_db

app = Flask(__name__)
app.secret_key = 'FocusTracker@2026#SecretKey$Render!'
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_NAME='focustracker_session'
)

# Initialize database
init_db()

# Trackers for Auto Alert Cooldown & Sleep Time
last_alert_time = {}
eyes_closed_counter = {}

def get_db():
    conn = sqlite3.connect('focustracker.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        class_name = request.form['class_name']
        password = request.form['password']
        
        conn = get_db()
        staff = conn.execute(
            'SELECT * FROM staff WHERE class_name = ? AND password = ?',
            (class_name, password)
        ).fetchone()
        conn.close()
        
        if staff:
            session['staff_id'] = staff['id']
            session['staff_name'] = staff['name']
            session['class_name'] = staff['class_name']
            return redirect(url_for('dashboard'))
        else:
            error = 'Invalid class or password!'
    return render_template('login.html', error=error)

@app.route('/dashboard')
def dashboard():
    if 'staff_id' not in session:
        return redirect(url_for('login'))
    return render_template('dashboard.html', 
                         staff_name=session['staff_name'],
                         class_name=session['class_name'])

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/forgot-password')
def forgot_password():
    return render_template('forgot_password.html')

@app.route('/students')
def students():
    if 'staff_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db()
    students_list = conn.execute(
        'SELECT * FROM students WHERE class_name = ?',
        (session['class_name'],)
    ).fetchall()
    conn.close()
    
    return render_template('students.html',
                         students=students_list,
                         class_name=session['class_name'])

@app.route('/students/add/<class_name>', methods=['POST'])
def add_student(class_name):
    register_no = request.form['register_no']
    name = request.form['name']
    
    conn = get_db()
    conn.execute(
        'INSERT INTO students (register_no, name, class_name) VALUES (?, ?, ?)',
        (register_no, name, class_name)
    )
    conn.commit()
    conn.close()
    return redirect(url_for('students'))

@app.route('/students/delete/<int:student_id>')
def delete_student(student_id):
    if 'staff_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db()
    conn.execute('DELETE FROM students WHERE id = ?', (student_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('students'))

@app.route('/start-session', methods=['GET', 'POST'])
def start_session():
    if 'staff_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        conn = get_db()
        now = datetime.now()
        conn.execute(
            'INSERT INTO sessions (staff_id, class_name, start_time, date) VALUES (?, ?, ?, ?)',
            (session['staff_id'], session['class_name'],
             now.strftime("%H:%M:%S"), now.strftime("%Y-%m-%d"))
        )
        conn.commit()
        session_id = conn.execute('SELECT last_insert_rowid()').fetchone()[0]
        conn.close()
        return jsonify({'session_id': session_id})
        
    conn = get_db()
    students_list = conn.execute(
        'SELECT * FROM students WHERE class_name = ?',
        (session['class_name'],)
    ).fetchall()
    conn.close()
    return render_template('session.html',
                         class_name=session['class_name'],
                         staff_name=session['staff_name'],
                         students=students_list)

@app.route('/process-frame', methods=['POST'])
def process_frame():
    global last_alert_time, eyes_closed_counter
    try:
        data = request.get_json()
        image_data = data.get('image', '').split(',')[1]
        session_id = data.get('session_id')
        
        # Decode base64 frame from frontend
        nparr = np.frombuffer(base64.b64decode(image_data), np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Classifiers for Face, Eyes, and Profile Face
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')
        
        # Detect Frontal Face
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(60, 60))
        
        status = "DISTRACTED"
        alert_to_log = None
        now_time = datetime.now()
        
        if len(faces) > 0:
            (x, y, w, h) = faces[0]
            roi_gray = gray[y:y+h, x:x+w]
            
            # Detect Eyes inside Face Region
            eyes = eye_cascade.detectMultiScale(roi_gray, scaleFactor=1.1, minNeighbors=3, minSize=(15, 15))
            
            if len(eyes) == 0:
                # Increment Eyes Closed Counter (Tracking ~5 sec closes)
                eyes_closed_counter[session_id] = eyes_closed_counter.get(session_id, 0) + 1
                if eyes_closed_counter[session_id] >= 6: # ~5-10 seconds threshold
                    status = "SLEEPING"
                    alert_to_log = "SLEEPING"
                else:
                    status = "FOCUSED"
            else:
                eyes_closed_counter[session_id] = 0
                status = "FOCUSED"
        else:
            # Check for Mobile/Object detection placeholder or posture threshold
            # High aspect ratio / hands raised towards face threshold
            eyes_closed_counter[session_id] = 0
            status = "DISTRACTED"
            alert_to_log = "DISTRACTED"
            
        # Automatic DB Alert Logging with 4-second cooldown to prevent flooding
        if alert_to_log and session_id:
            last_time = last_alert_time.get(session_id)
            if last_time is None or (now_time - last_time).total_seconds() >= 4:
                last_alert_time[session_id] = now_time
                conn = get_db()
                conn.execute(
                    'INSERT INTO alerts (session_id, register_no, student_name, alert_type, time) VALUES (?, ?, ?, ?, ?)',
                    (session_id, 'AUTO', 'AI Detector', alert_to_log, now_time.strftime("%H:%M:%S"))
                )
                conn.commit()
                conn.close()

        return jsonify({
            'status': 'success',
            'state': status
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/stop-session', methods=['POST'])
def stop_session():
    data = request.get_json()
    session_id = data.get('session_id')
        
    conn = get_db()
    conn.execute(
        'UPDATE sessions SET end_time = ? WHERE id = ?',
        (datetime.now().strftime("%H:%M:%S"), session_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'status': 'stopped'})

@app.route('/get-stats/<int:session_id>')
def get_stats(session_id):
    conn = get_db()
    alerts = conn.execute(
        'SELECT * FROM alerts WHERE session_id = ?',
        (session_id,)
    ).fetchall()
    conn.close()
    
    distracted = sum(1 for a in alerts if a['alert_type'] == 'DISTRACTED')
    sleeping = sum(1 for a in alerts if a['alert_type'] == 'SLEEPING')
    phone_use = sum(1 for a in alerts if a['alert_type'] == 'PHONE_USE')
    
    total = len(alerts)
    focus_percent = max(0, 100 - (total * 5))
    
    return jsonify({
        'focus_percent': focus_percent,
        'distracted': distracted,
        'sleeping': sleeping,
        'phone_use': phone_use,
        'alerts': [dict(a) for a in alerts]
    })

@app.route('/add-alert', methods=['POST'])
def add_alert():
    data = request.get_json()
    conn = get_db()
    conn.execute(
        'INSERT INTO alerts (session_id, register_no, student_name, alert_type, time) VALUES (?, ?, ?, ?, ?)',
        (data['session_id'], data['register_no'], data['student_name'],
         data['alert_type'], datetime.now().strftime("%H:%M:%S"))
    )
    conn.commit()
    conn.close()
    return jsonify({'status': 'added'})

@app.route('/reports')
def reports():
    if 'staff_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db()
    sessions_list = conn.execute(
        'SELECT * FROM sessions WHERE staff_id = ? ORDER BY id DESC',
        (session['staff_id'],)
    ).fetchall()
    
    sessions_with_alerts = []
    for s in sessions_list:
        alerts = conn.execute(
            'SELECT * FROM alerts WHERE session_id = ?',
            (s['id'],)
        ).fetchall()
        
        distracted = sum(1 for a in alerts if a['alert_type'] == 'DISTRACTED')
        sleeping = sum(1 for a in alerts if a['alert_type'] == 'SLEEPING')
        phone_use = sum(1 for a in alerts if a['alert_type'] == 'PHONE_USE')
        
        sessions_with_alerts.append({
            'id': s['id'],
            'date': s['date'],
            'start_time': s['start_time'],
            'end_time': s['end_time'],
            'class_name': s['class_name'],
            'distracted': distracted,
            'sleeping': sleeping,
            'phone_use': phone_use,
            'alerts': [dict(a) for a in alerts]
        })
    conn.close()
    
    return render_template('reports.html',
                         sessions=sessions_with_alerts,
                         class_name=session['class_name'])

@app.route('/download-report/<int:session_id>')
def download_report(session_id):
    if 'staff_id' not in session:
        return redirect(url_for('login'))
    
    conn = get_db()
    session_info = conn.execute(
        'SELECT * FROM sessions WHERE id = ?', (session_id,)
    ).fetchone()
    alerts = conn.execute(
        'SELECT * FROM alerts WHERE session_id = ?', (session_id,)
    ).fetchall()
    conn.close()
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []
    
    title = Paragraph(f"Focus Tracker Pro - Session Report", styles['Title'])
    elements.append(title)
    elements.append(Spacer(1, 10))
    
    info = Paragraph(
        f"Class: {session_info['class_name']} | "
        f"Date: {session_info['date']} | "
        f"Time: {session_info['start_time']} - {session_info['end_time'] or 'Ongoing'}",
        styles['Normal']
    )
    elements.append(info)
    elements.append(Spacer(1, 20))
    
    distracted = sum(1 for a in alerts if a['alert_type'] == 'DISTRACTED')
    sleeping = sum(1 for a in alerts if a['alert_type'] == 'SLEEPING')
    phone_use = sum(1 for a in alerts if a['alert_type'] == 'PHONE_USE')
    
    summary_data = [
        ['Alert Type', 'Count'],
        ['Distracted', str(distracted)],
        ['Sleeping', str(sleeping)],
        ['Phone Use', str(phone_use)],
        ['Total Alerts', str(len(alerts))]
    ]
    
    summary_table = Table(summary_data, colWidths=[200, 100])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e94560')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 1, colors.grey),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8f9fa')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), 
         [colors.HexColor('#f8f9fa'), colors.white]),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))
    
    if alerts:
        alert_heading = Paragraph("Alert Details", styles['Heading2'])
        elements.append(alert_heading)
        elements.append(Spacer(1, 10))
        
        alert_data = [['#', 'Register No', 'Student Name', 'Alert Type', 'Time']]
        for i, alert in enumerate(alerts, 1):
            alert_data.append([
                str(i),
                alert['register_no'],
                alert['student_name'],
                alert['alert_type'],
                alert['time']
            ])
        
        alert_table = Table(alert_data, colWidths=[30, 90, 150, 100, 80])
        alert_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f3460')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.white),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('GRID', (0,0), (-1,-1), 1, colors.grey),
            ('ROWBACKGROUNDS', (0,1), (-1,-1),
             [colors.HexColor('#f8f9fa'), colors.white]),
            ('FONTSIZE', (0,0), (-1,-1), 9),
        ]))
        elements.append(alert_table)
    else:
        elements.append(Paragraph("No alerts recorded.", styles['Normal']))
    
    doc.build(elements)
    buffer.seek(0)
    
    return send_file(
        buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'report_{session_info["class_name"]}_{session_info["date"]}.pdf'
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)