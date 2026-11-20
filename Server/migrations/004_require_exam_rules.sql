-- Existing exams without an assigned rule may retain their historical state.
ALTER TABLE exam_test ADD CONSTRAINT chk_exam_wiring_rules CHECK (
    (rule_filename IS NULL AND rule_snapshot IS NULL) OR
    (rule_filename IS NOT NULL AND REGEXP_LIKE(rule_filename, '[^[:space:]]')
     AND rule_snapshot IS NOT NULL AND JSON_SCHEMA_VALID(
        '{"type":"array","minItems":1,"items":{"type":"object","required":["nodes","score"],"properties":{"nodes":{"type":"array","minItems":2,"maxItems":2,"uniqueItems":true,"items":{"type":"string","minLength":1}},"score":{"type":"integer"}}}}',
        rule_snapshot))
);

DELIMITER $$
CREATE TRIGGER exam_require_rules_insert BEFORE INSERT ON exam_test FOR EACH ROW
BEGIN
    IF NEW.rule_filename IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '发布考试必须选择接线规则文件';
    END IF;
END$$

CREATE TRIGGER exam_keep_rules_update BEFORE UPDATE ON exam_test FOR EACH ROW
BEGIN
    IF OLD.rule_filename IS NOT NULL AND NEW.rule_filename IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = '考试已指定的接线规则不可清空';
    END IF;
END$$
DELIMITER ;
