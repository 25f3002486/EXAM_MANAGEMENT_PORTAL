# Examination Management Portal (EMP)

Flask + Jinja2 + Bootstrap 5 + SQLite web app where an **Admin**, **Examiners** and **Students** manage examinations, slots, bookings and evaluations. No JavaScript is used anywhere: every feature is a server-rendered form.

## Run locally

```bash
pip install -r requirements.txt
python seed.py --reset   # optional: demo courses, exams, users, bookings
python app.py            # http://127.0.0.1:5000
```

The SQLite database (`emp.db`) and all tables are created programmatically by `db.create_all()` when the app starts. The admin superuser is also seeded in code, and there is no admin registration.

| Role | Login | Password |
|---|---|---|
| Admin | admin@emp.com | admin123 |
| Examiner (demo) | anita@emp.com, vikram@emp.com, meera@emp.com | pass123 |
| Pending examiner (demo) | rohan@emp.com | pass123 |
| Student (demo) | aarav@student.emp.com, diya@student.emp.com, ishaan@…, kavya@…, rahul@…, sneha@… | pass123 |

## Project structure

```
app.py              app factory, Flask-Login setup, admin seeding, DB creation
models.py           SQLAlchemy models (all tables)
seed.py             optional demo data
routes/
  auth.py           login / register / logout / profile / pending-approval
  admin.py          dashboard, courses, exams, timeline control, rubrics, examiners,
                    students, slots, change examiner, bookings, reschedule, search
  examiner.py       dashboard, assigned exams, slot CRUD, booked students, evaluation
  student.py        dashboard, search/filter, book, cancel, history, results, scorecard
  api.py            JSON API (admin only)
  utils.py          role_required decorator, parsing helpers, booking audit log
templates/          Jinja2 templates (base layout + per-role folders)
static/style.css
```

## Database (ER summary)

| Table | Key columns | Relations |
|---|---|---|
| user | id, role, name, email, password_hash, phone, department, designation, roll_no, program, status | one table for admin/examiner/student |
| course | id, code (unique), name, description, credits, status | 1 course → N exams |
| exam | id, course_id, name, exam_type, duration, max_marks, pass_marks, slot_creation_start/end, booking_start/end, status, results_published | N exams ↔ N examiners (via exam_examiners); 1 exam → N rubrics, slots, bookings |
| exam_examiners | exam_id, examiner_id | association table for examiner assignment |
| rubric | id, exam_id, criterion, max_marks, weightage, description | N rubrics → 1 exam |
| slot | id, exam_id, examiner_id, date, start_time, end_time, venue, capacity, available_seats, status | N slots → 1 exam, 1 examiner |
| booking | id, student_id, slot_id, exam_id, booking_date, status, cancelled_at | N bookings → 1 student, 1 slot |
| booking_log | id, booking_id, action, details, actor_id, timestamp | audit trail per booking |
| evaluation | id, booking_id (unique), examiner_id, total_marks, remarks, evaluated_at | 1:1 with booking |
| evaluation_score | id, evaluation_id, rubric_id, marks | marks per rubric criterion |

## Business rules enforced in the backend

- An exam moves through **Draft → Slot Creation → Booking Open → Closed → Completed**. The admin controls each phase from the exam page.
- Examiners can create slots only for exams they are assigned to, only while the status is *Slot Creation*, and only within the slot-creation dates. Slots can't overlap, and each must be at least as long as the exam.
- Examiners can update or remove a slot only before booking starts and while nobody has booked it.
- Students can book only while the status is *Booking Open* and within the booking dates. Cancellation follows the same rule, so it is blocked once the booking deadline passes.
- Each student can have only one active booking per exam, and can't book two slots whose times clash.
- An atomic `UPDATE … WHERE available_seats > 0` prevents overbooking. A slot automatically becomes **Full** at capacity and returns to *Available* when someone cancels.
- Examiners can evaluate only bookings in their own slots. The total is computed from the rubric weightages, and evaluations lock once results are published.
- Students see results only after the admin publishes them. Results are shown with per-criterion marks and remarks, and the scorecard can be downloaded.
- The admin can reschedule a booking to another slot of the same exam, or reassign a slot (with all its students) to another examiner. Each action is written to `booking_log`. Exams that have bookings can't be deleted, so the history is kept.

## API endpoints (JSON, admin session required)

| Method | Endpoint | Description |
|---|---|---|
| GET | /api/stats | dashboard counts |
| GET | /api/exams[?status=] | list examinations |
| GET | /api/exams/&lt;id&gt; | exam with rubrics, examiners and slots |
| GET | /api/examiners | examiners |
| GET | /api/students | students |
| GET | /api/slots | all slots |
| GET | /api/bookings | all bookings, with marks |
