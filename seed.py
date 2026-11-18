import sys
from datetime import date, time, timedelta

from app import app, seed_admin
from models import db, User, Course, Exam, Rubric, Slot, Booking, BookingLog, Evaluation, EvaluationScore

T = date.today()


# Create a demo user with the default password
def user(role, name, email, **kw):
    u = User(role=role, name=name, email=email, status=kw.pop("status", "Active"), **kw)
    u.set_password("pass123")
    db.session.add(u)
    return u


# Populate the database with demo data
def run():
    if "--reset" in sys.argv:
        db.drop_all()
        db.create_all()
        seed_admin()
    if Course.query.first():
        print("Database already has data; use --reset to start over.")
        return

    e1 = user("examiner", "Dr. Anita Rao", "anita@emp.com", department="Computer Science", designation="Professor", phone="9876500001")
    e2 = user("examiner", "Prof. Vikram Shah", "vikram@emp.com", department="Computer Science", designation="Associate Professor", phone="9876500002")
    e3 = user("examiner", "Dr. Meera Iyer", "meera@emp.com", department="Mathematics", designation="Assistant Professor", phone="9876500003")
    user("examiner", "Mr. Rohan Das", "rohan@emp.com", department="Electronics", designation="Lecturer", status="Pending")
    students = [user("student", n, f"{n.split()[0].lower()}@student.emp.com", roll_no=f"21F{1000 + i}",
                     program="B.Sc. Data Science") for i, n in enumerate(
        ["Aarav Kumar", "Diya Patel", "Ishaan Gupta", "Kavya Nair", "Rahul Verma", "Sneha Reddy"])]

    c1 = Course(code="CS101", name="Programming in Python", description="Fundamentals of programming.", credits=4)
    c2 = Course(code="CS205", name="Modern Application Development", description="Web apps with Flask.", credits=4)
    c3 = Course(code="MA102", name="Statistics", description="Descriptive and inferential statistics.", credits=3)
    db.session.add_all([c1, c2, c3])

    x1 = Exam(course=c2, name="MAD-I Project Viva", exam_type="Viva", duration=20, max_marks=100, pass_marks=40,
              slot_creation_start=T - timedelta(10), slot_creation_end=T - timedelta(3),
              booking_start=T - timedelta(2), booking_end=T + timedelta(5), status="Booking Open",
              description="Bring your project and report.")
    x2 = Exam(course=c1, name="Python OPPE Practical", exam_type="Practical", duration=60, max_marks=50, pass_marks=20,
              slot_creation_start=T - timedelta(1), slot_creation_end=T + timedelta(4),
              booking_start=T + timedelta(5), booking_end=T + timedelta(10), status="Slot Creation")
    x3 = Exam(course=c3, name="Statistics Viva", exam_type="Viva", duration=15, max_marks=20, pass_marks=8,
              slot_creation_start=T - timedelta(40), slot_creation_end=T - timedelta(35),
              booking_start=T - timedelta(34), booking_end=T - timedelta(30), status="Completed",
              results_published=True)
    x4 = Exam(course=c2, name="MAD-II Project Demo", exam_type="Project Demo", duration=30, max_marks=100,
              status="Draft")
    db.session.add_all([x1, x2, x3, x4])
    x1.examiners, x2.examiners, x3.examiners = [e1, e2], [e1, e3], [e3]

    for ex, rows in ((x1, [("Functionality", 40, 40), ("Code quality", 20, 20), ("Viva answers", 40, 40)]),
                     (x2, [("Correctness", 30, 60), ("Efficiency", 10, 20), ("Style", 10, 20)]),
                     (x3, [("Concepts", 10, 50), ("Problem solving", 10, 50)])):
        for c, m, w in rows:
            db.session.add(Rubric(exam=ex, criterion=c, max_marks=m, weightage=w))
    db.session.flush()

    # Create a one-hour demo slot
    def slot(ex, ex_user, d, h, cap, venue="Room 101"):
        s = Slot(exam=ex, examiner=ex_user, date=d, start_time=time(h, 0), end_time=time(h + 1, 0),
                 capacity=cap, available_seats=cap, venue=venue, status="Available")
        db.session.add(s)
        return s

    s1 = slot(x1, e1, T + timedelta(7), 10, 2)
    s2 = slot(x1, e2, T + timedelta(7), 14, 3, "Online – Meet")
    slot(x1, e1, T + timedelta(8), 11, 4)
    s4 = slot(x3, e3, T - timedelta(25), 9, 5, "Room 204")
    db.session.flush()

    # Create a demo booking with a log entry
    def book(st, sl, status="Booked"):
        b = Booking(student=st, slot=sl, exam=sl.exam, status=status)
        db.session.add(b)
        db.session.add(BookingLog(booking=b, action="Booked", details=f"{sl.label}"))
        return b

    book(students[0], s1)
    book(students[1], s1)
    book(students[2], s2)
    for i, st in enumerate(students[:4]):
        b = book(st, s4, "Completed")
        marks = [7 + (i % 3), 6 + i % 4]
        ev = Evaluation(booking=b, examiner=e3, remarks=["Excellent clarity.", "Good, revise hypothesis testing.",
                                                         "Needs more practice.", "Solid answers."][i])
        ev.scores = [EvaluationScore(rubric=r, marks=m) for r, m in zip(x3.rubrics, marks)]
        ev.total_marks = round(20 * sum(m / r.max_marks * r.weightage for r, m in zip(x3.rubrics, marks)) / 100, 2)
        db.session.add(ev)
        db.session.add(BookingLog(booking=b, action="Evaluated", details=f"Marks: {ev.total_marks}/20"))
    db.session.flush()
    for s in Slot.query.all():
        s.refresh()
    s4.status = "Completed"
    db.session.commit()
    print("Demo data created. Logins (password pass123): anita@emp.com, vikram@emp.com, meera@emp.com, "
          "aarav@student.emp.com, diya@student.emp.com ... ; admin@emp.com / admin123")


if __name__ == "__main__":
    with app.app_context():
        run()
