ALTER TABLE exam_test
    ADD COLUMN issuer_tno INT UNSIGNED NULL,
    ADD COLUMN exam_content TEXT NULL,
    ADD COLUMN rule_filename VARCHAR(255) NULL,
    ADD COLUMN rule_snapshot JSON NULL,
    ADD CONSTRAINT fk_exam_issuer FOREIGN KEY (issuer_tno) REFERENCES teacher(tno)
        ON UPDATE CASCADE ON DELETE RESTRICT;

UPDATE exam_test e JOIN teacher t ON BINARY e.teacher_id = CAST(t.tno AS CHAR)
SET e.issuer_tno = t.tno, e.update_time = e.update_time;

CREATE TABLE teaching_class (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    teacher_tno INT UNSIGNED NOT NULL,
    name VARCHAR(100) NOT NULL,
    UNIQUE KEY uq_class_name (teacher_tno, name),
    CONSTRAINT fk_class_teacher FOREIGN KEY (teacher_tno) REFERENCES teacher(tno)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE class_student (
    class_id INT UNSIGNED NOT NULL,
    student_no INT UNSIGNED NOT NULL,
    PRIMARY KEY (class_id, student_no),
    CONSTRAINT fk_membership_class FOREIGN KEY (class_id) REFERENCES teaching_class(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_membership_student FOREIGN KEY (student_no) REFERENCES student(sno)
        ON UPDATE CASCADE ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
