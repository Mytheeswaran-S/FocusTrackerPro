import sqlite3

def init_db():
    conn = sqlite3.connect('focustracker.db')
    c = conn.cursor()
    
    # Staff table
    c.execute('''CREATE TABLE IF NOT EXISTS staff (
        id INTEGER PRIMARY KEY,
        name TEXT,
        class_name TEXT,
        password TEXT
    )''')
    
    # Students table
    c.execute('''CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY,
        register_no TEXT,
        name TEXT,
        class_name TEXT
    )''')
    
    # Sessions table
    c.execute('''CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY,
        staff_id INTEGER,
        class_name TEXT,
        start_time TEXT,
        end_time TEXT,
        date TEXT
    )''')
    
    # Alerts table
    c.execute('''CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY,
        session_id INTEGER,
        register_no TEXT,
        student_name TEXT,
        alert_type TEXT,
        time TEXT
    )''')
    
    # Insert staff initial data
    staff_data = [
        (1, 'Sathiyapriya', 'IT-A', 'Sathiya@ITA'),
        (2, 'Gowsalya', 'IT-B', 'Gowsalya@ITB'),
        (3, 'Sangeetha', 'IT-C', 'Sangeetha@ITC')
    ]
    
    c.executemany('''INSERT OR IGNORE INTO staff 
                     (id, name, class_name, password) 
                     VALUES (?, ?, ?, ?)''', staff_data)
    
    conn.commit()
    conn.close()
    print("Database created successfully!")

if __name__ == '__main__':
    init_db()