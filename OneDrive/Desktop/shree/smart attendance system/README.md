# Smart Student Attendance System

A small classroom attendance web app built with Python, Flask, SQLite, and QR codes. Teachers create courses and time-limited sessions. Students enroll with a course code, then check in by opening a QR link or entering the session code. Each student can check in only once per session. Teachers can download a CSV report.

## Features

- Teacher and student accounts with hashed passwords.
- Course creation and student enrollment codes.
- QR-link and short-code attendance check-in.
- Session expiry, enrollment checks, and duplicate prevention.
- Per-course attendance history and CSV export.
- SQLite storage, responsive interface, and CSRF protection.

## Requirements

- Windows 10/11, macOS, or Linux.
- Python 3.10 or later.
- A web browser. For phone QR testing, the phone and computer should use the same Wi-Fi.

## Setup on Windows

1. Install Python from [python.org](https://www.python.org/downloads/) and enable **Add Python to PATH** during setup.
2. Open this project folder in VS Code.
3. Open **Terminal → New Terminal**.
4. Create a virtual environment:

   ```powershell
   py -m venv .venv
   ```

5. Activate it:

   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```

   If PowerShell blocks activation, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that terminal, then activate again. Alternatively use Command Prompt and run `.venv\Scripts\activate.bat`.

6. Install dependencies:

   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

7. Start the website:

   ```powershell
   python app.py
   ```

8. Open <http://127.0.0.1:5000> in your browser. The SQLite database is created automatically in the `instance` folder on first start.

## First use

1. Create a **Teacher** account and sign in.
2. On the dashboard, enter a course title and subject/class code, then select **Create course**.
3. Copy the course's 8-character join code and give it to the class.
4. Open the course and create a session. Pick how long check-in should remain open.
5. Display the QR code or share the 6-character attendance code.
6. Each student creates a **Student** account, enters the course join code, then scans the QR code or types the attendance code on their dashboard.
7. The student reviews the course and confirms attendance. Refreshing or submitting twice cannot create a duplicate record.
8. Return to the course as its teacher and choose **Export CSV** to download the report. The report includes enrolled students as Present or Absent for every session.

## Test the project

With the virtual environment active, run:

```powershell
python -m pytest
```

## Test QR attendance on a phone

1. Find the computer's local IPv4 address with `ipconfig` (look for **IPv4 Address** on the active Wi-Fi adapter).
2. Stop the local server with `Ctrl+C`.
3. Start it so other devices on your network can reach it:

   ```powershell
   $env:FLASK_DEBUG = "0"
   python -m flask --app app run --host 0.0.0.0 --port 5000
   ```

4. On the computer, open `http://YOUR_IPV4_ADDRESS:5000` instead of `127.0.0.1`, sign in as the teacher, and open the session from that address. The QR code uses the address in the browser, so it will then point to the computer's network address.
5. Connect the phone to the same Wi-Fi, scan the QR code, sign in as an enrolled student, and confirm attendance. If Windows Firewall prompts you, allow Python on private networks.

## Project structure

```text
smart attendance system/
|-- app.py                 Flask routes, database schema, and business rules
|-- requirements.txt       Python dependencies
|-- instance/              SQLite database (generated on first run)
|-- templates/             Jinja HTML pages
|-- static/style.css       Responsive styling
|-- tests/test_app.py      Attendance workflow integration test
|-- README.md              Setup and usage guide
```

## Notes for a class demo

- This is a local academic prototype, not a production attendance platform. For deployment, set a long random `SECRET_KEY` environment variable, use HTTPS, add account verification and password reset, and configure a production WSGI server.
- QR check-in is a possession-based classroom check-in, not identity verification or proof of physical presence. A student could share a code/link while its session is open.
- Times in the attendance report are stored and shown in UTC.
- To reset demo data, stop the app and delete `instance/attendance.sqlite3`; it will be recreated on the next launch.