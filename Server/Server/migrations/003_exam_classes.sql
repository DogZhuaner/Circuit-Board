-- Existing exams were published to all students. New exams require class membership.
ALTER TABLE exam_test ADD COLUMN class_restricted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE exam_test ALTER COLUMN class_restricted SET DEFAULT TRUE;

CREATE TABLE exam_class (
    exam_id INT NOT NULL,
    class_id INT UNSIGNED NOT NULL,
    PRIMARY KEY (exam_id, class_id),
    CONSTRAINT fk_audience_exam FOREIGN KEY (exam_id) REFERENCES exam_test(id) ON DELETE CASCADE,
    CONSTRAINT fk_audience_class FOREIGN KEY (class_id) REFERENCES teaching_class(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
