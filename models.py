from datetime import datetime, date

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

exam_examiners = db.Table(
    "exam_examiners",
    db.Column("exam_id", db.Integer, db.ForeignKey("exam.id"), primary_key=True),
    db.Column("examiner_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    phone = db.Column(db.String(20))
    department = db.Column(db.String(120))
    designation = db.Column(db.String(120))
    roll_no = db.Column(db.String(40), unique=True)
    program = db.Column(db.String(120))
    status = db.Column(db.String(20), nullable=False, default="Active")
    created_at = db.Column(db.DateTime, default=datetime.now)

    slots = db.relationship("Slot", back_populates="examiner", foreign_keys="Slot.examiner_id")
    bookings = db.relationship("Booking", back_populates="student", foreign_keys="Booking.student_id")
    assigned_exams = db.relationship("Exam", secondary=exam_examiners, back_populates="examiners")

    # Hash and store the user's password
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    # Verify a password against the stored hash
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # Return the user's role-prefixed display code
    @property
    def code(self):
        prefix = {"admin": "ADM", "examiner": "EXR", "student": "STU"}[self.role]
        return f"{prefix}{self.id:04d}"


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    credits = db.Column(db.Integer)
    status = db.Column(db.String(20), nullable=False, default="Active")
    created_at = db.Column(db.DateTime, default=datetime.now)

    exams = db.relationship("Exam", back_populates="course")


EXAM_TYPES = ["Viva", "Practical", "Project Demo", "Assessment"]
EXAM_STATUSES = ["Draft", "Slot Creation", "Booking Open", "Closed", "Completed"]


class Exam(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    exam_type = db.Column(db.String(30), nullable=False)
    description = db.Column(db.Text)
    duration = db.Column(db.Integer, nullable=False)
    max_marks = db.Column(db.Float, nullable=False)
    pass_marks = db.Column(db.Float)
    slot_creation_start = db.Column(db.Date)
    slot_creation_end = db.Column(db.Date)
    booking_start = db.Column(db.Date)
    booking_end = db.Column(db.Date)
    status = db.Column(db.String(20), nullable=False, default="Draft")
    results_published = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    course = db.relationship("Course", back_populates="exams")
    rubrics = db.relationship("Rubric", back_populates="exam", cascade="all, delete-orphan")
    slots = db.relationship("Slot", back_populates="exam", cascade="all, delete-orphan")
    examiners = db.relationship("User", secondary=exam_examiners, back_populates="assigned_exams")

    # Return the exam's display code
    @property
    def code(self):
        return f"EXM{self.id:04d}"

    # Check whether today falls within a date window
    @staticmethod
    def _within(start, end, today=None):
        today = today or date.today()
        if start and today < start:
            return False
        if end and today > end:
            return False
        return True

    # Check whether examiners can currently create slots
    @property
    def slot_creation_allowed(self):
        return self.status == "Slot Creation" and self._within(self.slot_creation_start, self.slot_creation_end)

    # Check whether students can currently book slots
    @property
    def booking_allowed(self):
        return self.status == "Booking Open" and self._within(self.booking_start, self.booking_end)

    # Check whether the booking phase has begun
    @property
    def booking_started(self):
        return self.status in ("Booking Open", "Completed") or (
            self.booking_start is not None and date.today() >= self.booking_start
        )

    # Sum the weightage of all exam rubrics
    @property
    def rubric_total_weight(self):
        return sum(r.weightage for r in self.rubrics)


class Rubric(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exam.id"), nullable=False)
    criterion = db.Column(db.String(150), nullable=False)
    max_marks = db.Column(db.Float, nullable=False)
    weightage = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)

    exam = db.relationship("Exam", back_populates="rubrics")


SLOT_STATUSES = ["Available", "Full", "Cancelled", "Completed"]


class Slot(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exam.id"), nullable=False)
    examiner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    venue = db.Column(db.String(150))
    capacity = db.Column(db.Integer, nullable=False)
    available_seats = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), nullable=False, default="Available")
    created_at = db.Column(db.DateTime, default=datetime.now)

    exam = db.relationship("Exam", back_populates="slots")
    examiner = db.relationship("User", back_populates="slots", foreign_keys=[examiner_id])
    bookings = db.relationship("Booking", back_populates="slot")

    # Return the slot's display code
    @property
    def code(self):
        return f"SLT{self.id:04d}"

    # List bookings that are booked or completed
    @property
    def active_bookings(self):
        return [b for b in self.bookings if b.status in ("Booked", "Completed")]

    # Recompute available seats and update slot status
    def refresh(self):
        self.available_seats = max(self.capacity - len(self.active_bookings), 0)
        if self.status in ("Cancelled", "Completed"):
            return
        self.status = "Full" if self.available_seats == 0 else "Available"

    # Check whether the examiner may still edit slot
    @property
    def editable(self):
        return (not self.exam.booking_started and not self.active_bookings
                and self.status not in ("Cancelled", "Completed"))

    # Return a readable date and time label
    @property
    def label(self):
        return f"{self.date:%d %b %Y}, {self.start_time:%H:%M}-{self.end_time:%H:%M}"


BOOKING_STATUSES = ["Booked", "Cancelled", "Completed"]


class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    slot_id = db.Column(db.Integer, db.ForeignKey("slot.id"), nullable=False)
    exam_id = db.Column(db.Integer, db.ForeignKey("exam.id"), nullable=False)
    booking_date = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(20), nullable=False, default="Booked")
    cancelled_at = db.Column(db.DateTime)

    student = db.relationship("User", back_populates="bookings", foreign_keys=[student_id])
    slot = db.relationship("Slot", back_populates="bookings")
    exam = db.relationship("Exam")
    evaluation = db.relationship("Evaluation", back_populates="booking", uselist=False,
                                 cascade="all, delete-orphan")
    logs = db.relationship("BookingLog", back_populates="booking", order_by="BookingLog.timestamp",
                           cascade="all, delete-orphan")

    # Return the booking's display code
    @property
    def code(self):
        return f"BKG{self.id:04d}"


class BookingLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), nullable=False)
    action = db.Column(db.String(40), nullable=False)
    details = db.Column(db.String(300))
    actor_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    timestamp = db.Column(db.DateTime, default=datetime.now)

    booking = db.relationship("Booking", back_populates="logs")
    actor = db.relationship("User")


class Evaluation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey("booking.id"), unique=True, nullable=False)
    examiner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    total_marks = db.Column(db.Float, nullable=False)
    remarks = db.Column(db.Text)
    evaluated_at = db.Column(db.DateTime, default=datetime.now)

    booking = db.relationship("Booking", back_populates="evaluation")
    examiner = db.relationship("User")
    scores = db.relationship("EvaluationScore", back_populates="evaluation", cascade="all, delete-orphan")


class EvaluationScore(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    evaluation_id = db.Column(db.Integer, db.ForeignKey("evaluation.id"), nullable=False)
    rubric_id = db.Column(db.Integer, db.ForeignKey("rubric.id"), nullable=False)
    marks = db.Column(db.Float, nullable=False)

    evaluation = db.relationship("Evaluation", back_populates="scores")
    rubric = db.relationship("Rubric")
