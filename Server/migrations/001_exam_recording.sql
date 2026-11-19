CREATE TABLE IF NOT EXISTS exam_recording (
    result_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    recording_id CHAR(32) CHARACTER SET ascii NOT NULL UNIQUE,
    sha256 CHAR(64) CHARACTER SET ascii NOT NULL,
    CONSTRAINT fk_recording_result FOREIGN KEY (result_id) REFERENCES exam_result(id)
) ENGINE=InnoDB;
