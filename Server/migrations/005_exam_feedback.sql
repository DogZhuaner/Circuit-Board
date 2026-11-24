CREATE TABLE IF NOT EXISTS exam_result_summary (
    result_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    facts JSON NOT NULL,
    CONSTRAINT fk_summary_result FOREIGN KEY (result_id) REFERENCES exam_result(id) ON DELETE CASCADE
) ENGINE=InnoDB;
