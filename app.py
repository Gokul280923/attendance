from flask import Flask, render_template, request, flash, url_for, jsonify
import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager
from collections import defaultdict

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "static/uploads"
app.secret_key = 'ferrocon@123'

# Ensure the upload folder exists
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Database configuration
DATABASE_PATH = "data.db"

def get_db():
    """Create a database connection and return the connection and cursor"""
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        raise Exception(f"Database connection error: {e}")

@contextmanager
def get_db_cursor():
    """Context manager for database operations"""
    conn = get_db()
    try:
        cursor = conn.cursor()
        yield cursor
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

def init_db():
    """Initialize the database with required tables"""
    with get_db_cursor() as cursor:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT UNIQUE,
            aadhar TEXT UNIQUE,
            role TEXT,
            photo TEXT,
            wage DECIMAL(10,2) DEFAULT 0.00
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            is_present BOOLEAN NOT NULL,
            is_half_day BOOLEAN DEFAULT FALSE,
            overtime_hours FLOAT DEFAULT 0,
            FOREIGN KEY (worker_id) REFERENCES workers (id),
            UNIQUE(worker_id, date)
        )
        """)

# Initialize database when starting the application
init_db()

def calculate_department_analytics():
    """Calculate department-wise expenditure for the pie chart"""
    with get_db_cursor() as cursor:
        cursor.execute("""
        SELECT 
            w.role as department,
            SUM(
                CASE 
                    WHEN a.is_present AND NOT a.is_half_day THEN w.wage
                    WHEN a.is_present AND a.is_half_day THEN w.wage / 2
                    ELSE 0
                END + 
                (a.overtime_hours * (w.wage / 9))
            ) as total_expenditure
        FROM workers w
        LEFT JOIN attendance a ON w.id = a.worker_id
        WHERE w.role IS NOT NULL
        GROUP BY w.role
        """)
        results = cursor.fetchall()
        
        department_labels = [row['department'] for row in results]
        department_values = [float(row['total_expenditure']) for row in results]
        
        return department_labels, department_values

def calculate_total_wages():
    """Calculate total wages including normal and overtime"""
    with get_db_cursor() as cursor:
        cursor.execute("""
        SELECT 
            SUM(
                CASE 
                    WHEN a.is_present AND NOT a.is_half_day THEN w.wage
                    WHEN a.is_present AND a.is_half_day THEN w.wage / 2
                    ELSE 0
                END
            ) as total_normal_wage,
            SUM(a.overtime_hours * (w.wage / 9)) as total_ot_wage
        FROM workers w
        LEFT JOIN attendance a ON w.id = a.worker_id
        """)
        result = cursor.fetchone()
        
        total_normal_wage = float(result['total_normal_wage'] or 0)
        total_ot_wage = float(result['total_ot_wage'] or 0)
        total_expenditure = total_normal_wage + total_ot_wage
        
        return total_normal_wage, total_ot_wage, total_expenditure

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/update_worker", methods=["POST"])
def update_worker():
    try:
        data = request.get_json()
        worker_id = data.get('worker_id')
        role = data.get('role')
        wage = data.get('wage')

        with get_db_cursor() as cursor:
            cursor.execute("""
                UPDATE workers 
                SET role = ?, wage = ?
                WHERE id = ?
            """, (role, wage, worker_id))
            
            cursor.execute("SELECT name FROM workers WHERE id = ?", (worker_id,))
            worker = cursor.fetchone()
            
            return jsonify({
                'success': True,
                'name': worker['name']
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 400

@app.route("/add_remove_worker", methods=["GET", "POST"])
def add_remove_worker():
    if request.method == "POST":
        if request.form.get("action") == "Add":
            name = request.form["name"]
            phone = request.form["phone"]
            aadhar = request.form["aadhar"]
            role = request.form["role"]
            wage = request.form["wage"]
            photo = request.files["photo"]

            try:
                photo_path = os.path.join(app.config["UPLOAD_FOLDER"], photo.filename)
                photo.save(photo_path)

                with get_db_cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO workers (name, phone, aadhar, role, photo, wage) VALUES (?, ?, ?, ?, ?, ?)",
                        (name, phone, aadhar, role, photo_path, wage)
                    )
                flash('Worker added successfully!', 'success')
            except sqlite3.IntegrityError:
                flash('Duplicate entry detected! Phone or Aadhar already exists.', 'error')
            except Exception as e:
                flash(f'Error adding worker: {str(e)}', 'error')

        elif request.form.get("action") == "Remove":
            worker_id = request.form["worker_id"]
            try:
                with get_db_cursor() as cursor:
                    cursor.execute("DELETE FROM attendance WHERE worker_id = ?", (worker_id,))
                    cursor.execute("DELETE FROM workers WHERE id = ?", (worker_id,))
                flash('Worker removed successfully!', 'success')
            except Exception as e:
                flash(f'Error removing worker: {str(e)}', 'error')

    with get_db_cursor() as cursor:
        cursor.execute("SELECT * FROM workers ORDER BY name")
        workers = cursor.fetchall()
    return render_template("add_remove_worker.html", workers=workers)

@app.route("/add_remove_attendance", methods=["GET", "POST"])
def add_remove_attendance():
    if request.method == "POST":
        date = request.form["attendance_date"]
        
        try:
            with get_db_cursor() as cursor:
                # First check if there are any existing entries for this date
                cursor.execute("SELECT worker_id FROM attendance WHERE date = ?", (date,))
                existing_entries = cursor.fetchall()
                
                if existing_entries:
                    flash(f'Attendance for {date} already exists. Please edit the existing entry instead.', 'error')
                    return redirect(url_for('add_remove_attendance'))
                
                cursor.execute("SELECT id FROM workers")
                worker_ids = cursor.fetchall()
                
                for worker_id in worker_ids:
                    worker_id = worker_id[0]
                    present_key = f"present_{worker_id}"
                    half_day_key = f"half_day_{worker_id}"
                    absent_key = f"absent_{worker_id}"
                    overtime_key = f"overtime_{worker_id}"
                    
                    # Handle attendance status
                    is_present = present_key in request.form
                    is_half_day = half_day_key in request.form
                    is_absent = absent_key in request.form
                    
                    # Handle overtime independently
                    overtime_hours = float(request.form.get(overtime_key, 0) or 0)
                    
                    cursor.execute("""
                        INSERT INTO attendance (worker_id, date, is_present, is_half_day, overtime_hours)
                        VALUES (?, ?, ?, ?, ?)
                    """, (worker_id, date, is_present, is_half_day, overtime_hours))
                
            flash('Attendance recorded successfully!', 'success')
            
        except Exception as e:
            flash(f'Error recording attendance: {str(e)}', 'error')
    
    with get_db_cursor() as cursor:
        cursor.execute("SELECT * FROM workers ORDER BY name")
        workers = cursor.fetchall()
        
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("""
            SELECT w.id, w.name, w.role, w.wage,
                   COALESCE(a.is_present, 0) as is_present, 
                   COALESCE(a.is_half_day, 0) as is_half_day, 
                   COALESCE(a.overtime_hours, 0) as overtime_hours
            FROM workers w
            LEFT JOIN attendance a ON w.id = a.worker_id AND a.date = ?
            ORDER BY w.name
        """, (today,))
        attendance_data = cursor.fetchall()
    
    return render_template("add_remove_attendance.html", 
                         workers=workers,
                         attendance_data=attendance_data)

@app.route("/view_attendance")
def view_attendance():
    selected_department = request.args.get('department', 'all')  # Default to 'all'
    
    with get_db_cursor() as cursor:
        # Get unique departments for the dropdown
        cursor.execute("SELECT DISTINCT role FROM workers WHERE role IS NOT NULL ORDER BY role")
        unique_departments = [row['role'] for row in cursor.fetchall()]
        
        # Base query with department filter - Only for attendance records table
        department_filter = "AND w.role = ?" if selected_department != 'all' else ""
        department_params = [selected_department] if selected_department != 'all' else []
        
        # Calculate attendance statistics - With department filter
        cursor.execute(f"""
        WITH AttendanceStats AS (
            SELECT 
                worker_id,
                SUM(CASE WHEN is_present = 1 AND is_half_day = 0 THEN 1 ELSE 0 END) as full_days,
                SUM(CASE WHEN is_present = 1 AND is_half_day = 1 THEN 1 ELSE 0 END) as half_days,
                SUM(COALESCE(overtime_hours, 0)) as total_ot_hours,
                CAST(COUNT(CASE WHEN is_present = 1 THEN 1 END) AS FLOAT) * 100 / 
                    CAST(COUNT(*) AS FLOAT) as attendance_percentage
            FROM attendance
            GROUP BY worker_id
        )
        SELECT 
            w.id,
            w.name,
            w.photo,
            w.role as department,
            w.wage,
            COALESCE(a.full_days, 0) as full_days,
            COALESCE(a.half_days, 0) as half_days,
            COALESCE(a.total_ot_hours, 0) as total_ot_hours,
            COALESCE(a.attendance_percentage, 0) as attendance_percentage
        FROM workers w
        LEFT JOIN AttendanceStats a ON w.id = a.worker_id
        WHERE 1=1 {department_filter}
        ORDER BY w.name
        """, department_params)
        
        attendance_records = []
        for record in cursor.fetchall():
            daily_wage = record['wage']
            ot_rate = daily_wage / 9
            normal_wage = (record['full_days'] * daily_wage) + (record['half_days'] * daily_wage / 2)
            ot_wage = record['total_ot_hours'] * ot_rate
            total_wage = normal_wage + ot_wage

            attendance_records.append({
                'id': record['id'],
                'name': record['name'],
                'photo': record['photo'],
                'department': record['department'],
                'full_days': record['full_days'],
                'half_days': record['half_days'],
                'total_ot_hours': record['total_ot_hours'],
                'attendance_percentage': record['attendance_percentage'],
                'normal_wage': normal_wage,
                'ot_wage': ot_wage,
                'total_wage': total_wage
            })

        # Calculate department expenditure - No filter, show all departments
        cursor.execute("""
        SELECT 
            w.role as department,
            SUM(
                CASE 
                    WHEN a.is_present AND NOT a.is_half_day THEN w.wage
                    WHEN a.is_present AND a.is_half_day THEN w.wage / 2
                    ELSE 0
                END + 
                (COALESCE(a.overtime_hours, 0) * (w.wage / 9))
            ) as total_expenditure
        FROM workers w
        LEFT JOIN attendance a ON w.id = a.worker_id
        WHERE w.role IS NOT NULL
        GROUP BY w.role
        """)
        dept_results = cursor.fetchall()

        # Calculate OT hours by department - No filter, show all departments
        cursor.execute("""
        SELECT 
            w.role as department,
            SUM(COALESCE(a.overtime_hours, 0)) as total_ot_hours
        FROM workers w
        LEFT JOIN attendance a ON w.id = a.worker_id
        WHERE w.role IS NOT NULL
        GROUP BY w.role
        """)
        ot_results = cursor.fetchall()

        # Calculate total wages - No filter, show overall totals
        cursor.execute("""
        SELECT 
            SUM(
                CASE 
                    WHEN a.is_present AND NOT a.is_half_day THEN w.wage
                    WHEN a.is_present AND a.is_half_day THEN w.wage / 2
                    ELSE 0
                END
            ) as total_normal_wage,
            SUM(COALESCE(a.overtime_hours, 0) * (w.wage / 9)) as total_ot_wage
        FROM workers w
        LEFT JOIN attendance a ON w.id = a.worker_id
        """)
        wage_result = cursor.fetchone()

        department_labels = [row['department'] for row in dept_results]
        department_values = [float(row['total_expenditure']) for row in dept_results]
        
        ot_hours_labels = [row['department'] for row in ot_results]
        ot_hours_values = [float(row['total_ot_hours']) for row in ot_results]
        
        total_normal_wage = float(wage_result['total_normal_wage'] or 0)
        total_ot_wage = float(wage_result['total_ot_wage'] or 0)
        total_expenditure = total_normal_wage + total_ot_wage

    return render_template("view_attendance.html", 
                         attendance_records=attendance_records,
                         department_labels=department_labels,
                         department_values=department_values,
                         ot_hours_labels=ot_hours_labels,
                         ot_hours_values=ot_hours_values,
                         total_normal_wage=total_normal_wage,
                         total_ot_wage=total_ot_wage,
                         total_expenditure=total_expenditure,
                         unique_departments=unique_departments,
                         selected_department=selected_department)  # Pass selected department to template

@app.route("/get_filtered_data")
def get_filtered_data():
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    
    with get_db_cursor() as cursor:
        # Get filtered attendance data
        cursor.execute("""
        WITH AttendanceStats AS (
            SELECT 
                worker_id,
                SUM(CASE WHEN is_present = 1 AND is_half_day = 0 THEN 1 ELSE 0 END) as full_days,
                SUM(CASE WHEN is_present = 1 AND is_half_day = 1 THEN 1 ELSE 0 END) as half_days,
                SUM(COALESCE(overtime_hours, 0)) as total_ot_hours,
                CAST(COUNT(CASE WHEN is_present = 1 THEN 1 END) AS FLOAT) * 100 / 
                    CAST(COUNT(*) AS FLOAT) as attendance_percentage
            FROM attendance
            WHERE date BETWEEN ? AND ?
            GROUP BY worker_id
        )
        SELECT 
            w.id,
            w.name,
            w.photo,
            w.role as department,
            w.wage,
            COALESCE(a.full_days, 0) as full_days,
            COALESCE(a.half_days, 0) as half_days,
            COALESCE(a.total_ot_hours, 0) as total_ot_hours,
            COALESCE(a.attendance_percentage, 0) as attendance_percentage
        FROM workers w
        LEFT JOIN AttendanceStats a ON w.id = a.worker_id
        ORDER BY w.name
        """, (date_from, date_to))
        
        attendance_data = cursor.fetchall()

        # Calculate department analytics for filtered date range
        cursor.execute("""
        SELECT 
            w.role as department,
            SUM(
                CASE 
                    WHEN a.is_present AND NOT a.is_half_day THEN w.wage
                    WHEN a.is_present AND a.is_half_day THEN w.wage / 2
                    ELSE 0
                END + 
                (COALESCE(a.overtime_hours, 0) * (w.wage / 9))
            ) as total_expenditure
        FROM workers w
        LEFT JOIN attendance a ON w.id = a.worker_id
        WHERE w.role IS NOT NULL
        AND date BETWEEN ? AND ?
        GROUP BY w.role
        """, (date_from, date_to))
        dept_results = cursor.fetchall()

        # Calculate OT hours by department for filtered date range
        cursor.execute("""
        SELECT 
            w.role as department,
            SUM(COALESCE(a.overtime_hours, 0)) as total_ot_hours
        FROM workers w
        LEFT JOIN attendance a ON w.id = a.worker_id
        WHERE w.role IS NOT NULL
        AND date BETWEEN ? AND ?
        GROUP BY w.role
        """, (date_from, date_to))
        ot_results = cursor.fetchall()

        # Calculate total wages for filtered date range
        cursor.execute("""
        SELECT 
            SUM(
                CASE 
                    WHEN a.is_present AND NOT a.is_half_day THEN w.wage
                    WHEN a.is_present AND a.is_half_day THEN w.wage / 2
                    ELSE 0
                END
            ) as total_normal_wage,
            SUM(COALESCE(a.overtime_hours, 0) * (w.wage / 9)) as total_ot_wage
        FROM workers w
        LEFT JOIN attendance a ON w.id = a.worker_id
        WHERE date BETWEEN ? AND ?
        """, (date_from, date_to))
        wage_result = cursor.fetchone()

        # Process the results
        attendance_records = []
        for record in attendance_data:
            daily_wage = record['wage']
            ot_rate = daily_wage / 9
            normal_wage = (record['full_days'] * daily_wage) + (record['half_days'] * daily_wage / 2)
            ot_wage = record['total_ot_hours'] * ot_rate
            total_wage = normal_wage + ot_wage

            attendance_records.append({
                'id': record['id'],
                'name': record['name'],
                'photo': record['photo'],
                'department': record['department'],
                'full_days': record['full_days'],
                'half_days': record['half_days'],
                'total_ot_hours': record['total_ot_hours'],
                'attendance_percentage': record['attendance_percentage'],
                'normal_wage': normal_wage,
                'ot_wage': ot_wage,
                'total_wage': total_wage
            })

        department_labels = [row['department'] for row in dept_results]
        department_values = [float(row['total_expenditure']) for row in dept_results]
        
        ot_hours_labels = [row['department'] for row in ot_results]
        ot_hours_values = [float(row['total_ot_hours']) for row in ot_results]
        
        total_normal_wage = float(wage_result['total_normal_wage'] or 0)
        total_ot_wage = float(wage_result['total_ot_wage'] or 0)
        total_expenditure = total_normal_wage + total_ot_wage

        return jsonify({
            'attendance_records': attendance_records,
            'department_labels': department_labels,
            'department_values': department_values,
            'ot_hours_labels': ot_hours_labels,
            'ot_hours_values': ot_hours_values,
            'total_normal_wage': total_normal_wage,
            'total_ot_wage': total_ot_wage,
            'total_expenditure': total_expenditure
        })

        # Calculate department analytics for filtered date range
        cursor.execute("""
        SELECT 
            w.role as department,
            SUM(
                CASE 
                    WHEN a.is_present AND NOT a.is_half_day THEN w.wage
                    WHEN a.is_present AND a.is_half_day THEN w.wage / 2
                    ELSE 0
                END + 
                (COALESCE(a.overtime_hours, 0) * (w.wage / 9))
            ) as total_expenditure
        FROM workers w
        LEFT JOIN attendance a ON w.id = a.worker_id
        WHERE w.role IS NOT NULL
        AND date BETWEEN ? AND ?
        GROUP BY w.role
        """, (date_from, date_to))
        dept_results = cursor.fetchall()

        # Calculate total wages for filtered date range
        cursor.execute("""
        SELECT 
            SUM(
                CASE 
                    WHEN a.is_present AND NOT a.is_half_day THEN w.wage
                    WHEN a.is_present AND a.is_half_day THEN w.wage / 2
                    ELSE 0
                END
            ) as total_normal_wage,
            SUM(COALESCE(a.overtime_hours, 0) * (w.wage / 9)) as total_ot_wage
        FROM workers w
        LEFT JOIN attendance a ON w.id = a.worker_id
        WHERE date BETWEEN ? AND ?
        """, (date_from, date_to))
        wage_result = cursor.fetchone()

        # Process the results
        attendance_records = []
        for record in attendance_data:
            daily_wage = record['wage']
            ot_rate = daily_wage / 9
            normal_wage = (record['full_days'] * daily_wage) + (record['half_days'] * daily_wage / 2)
            ot_wage = record['total_ot_hours'] * ot_rate
            total_wage = normal_wage + ot_wage

            attendance_records.append({
                'id': record['id'],
                'name': record['name'],
                'photo': record['photo'],
                'department': record['department'],
                'full_days': record['full_days'],
                'half_days': record['half_days'],
                'total_ot_hours': record['total_ot_hours'],
                'attendance_percentage': record['attendance_percentage'],
                'normal_wage': normal_wage,
                'ot_wage': ot_wage,
                'total_wage': total_wage
            })

        department_labels = [row['department'] for row in dept_results]
        department_values = [float(row['total_expenditure']) for row in dept_results]
        
        total_normal_wage = float(wage_result['total_normal_wage'] or 0)
        total_ot_wage = float(wage_result['total_ot_wage'] or 0)
        total_expenditure = total_normal_wage + total_ot_wage

        return jsonify({
            'attendance_records': attendance_records,
            'department_labels': department_labels,
            'department_values': department_values,
            'total_normal_wage': total_normal_wage,
            'total_ot_wage': total_ot_wage,
            'total_expenditure': total_expenditure
        })
if __name__ == '__main__':
    app.run(debug=False,host="0.0.0.0")
