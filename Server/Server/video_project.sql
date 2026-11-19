-- MySQL dump 10.13  Distrib 8.0.46, for Win64 (x86_64)
--
-- Host: 127.0.0.1    Database: video_project
-- ------------------------------------------------------
-- Server version	8.0.46

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `exam_result`
--

DROP TABLE IF EXISTS `exam_result`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `exam_result` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `student_no` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `student_name` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `test_id` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `test_name` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `test_score` decimal(7,2) DEFAULT NULL,
  `knowledge` text COLLATE utf8mb4_unicode_ci,
  `created_at` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_exam_result_test` (`test_id`,`id`),
  KEY `idx_exam_result_student` (`student_no`,`id`)
) ENGINE=InnoDB AUTO_INCREMENT=17 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

DROP TABLE IF EXISTS exam_recording;
CREATE TABLE IF NOT EXISTS exam_recording (
    result_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
    recording_id CHAR(32) CHARACTER SET ascii NOT NULL UNIQUE,
    sha256 CHAR(64) CHARACTER SET ascii NOT NULL,
    CONSTRAINT fk_recording_result FOREIGN KEY (result_id) REFERENCES exam_result(id)
) ENGINE=InnoDB;

--
-- Dumping data for table `exam_result`
--

LOCK TABLES `exam_result` WRITE;
/*!40000 ALTER TABLE `exam_result` DISABLE KEYS */;
INSERT INTO `exam_result` VALUES (1,'DEMO-001','演示学员01','DEMO-202611-SELFLOCK','【演示】2026年11月 自锁与互锁控制',92.00,'','2026-11-07 11:46:18'),(2,'DEMO-002','演示学员02','DEMO-202611-SELFLOCK','【演示】2026年11月 自锁与互锁控制',78.00,'自锁、互锁','2026-11-07 11:46:18'),(3,'DEMO-003','演示学员03','DEMO-202611-SELFLOCK','【演示】2026年11月 自锁与互锁控制',65.00,'自锁、过载','2026-11-07 11:46:18'),(4,'DEMO-004','演示学员04','DEMO-202611-SELFLOCK','【演示】2026年11月 自锁与互锁控制',84.00,'互锁','2026-11-07 11:46:18'),(5,'DEMO-005','演示学员05','DEMO-202611-SELFLOCK','【演示】2026年11月 自锁与互锁控制',58.00,'自锁、互锁、过载','2026-11-07 11:46:18'),(6,'DEMO-006','演示学员06','DEMO-202611-SELFLOCK','【演示】2026年11月 自锁与互锁控制',73.00,'过载','2026-11-07 11:46:18'),(7,'DEMO-007','演示学员07','DEMO-202611-SELFLOCK','【演示】2026年11月 自锁与互锁控制',89.00,'互锁','2026-11-07 11:46:18'),(8,'DEMO-008','演示学员08','DEMO-202611-SELFLOCK','【演示】2026年11月 自锁与互锁控制',61.00,'自锁、过载','2026-11-07 11:46:18'),(9,'DEMO-001','演示学员01','DEMO-202611-SEQUENCE','【演示】2026年11月 顺序控制与过载保护',88.00,'顺序','2026-11-07 11:46:18'),(10,'DEMO-002','演示学员02','DEMO-202611-SEQUENCE','【演示】2026年11月 顺序控制与过载保护',71.00,'顺序、过载','2026-11-07 11:46:18'),(11,'DEMO-003','演示学员03','DEMO-202611-SEQUENCE','【演示】2026年11月 顺序控制与过载保护',55.00,'顺序、过载','2026-11-07 11:46:18'),(12,'DEMO-004','演示学员04','DEMO-202611-SEQUENCE','【演示】2026年11月 顺序控制与过载保护',94.00,'','2026-11-07 11:46:18'),(13,'DEMO-005','演示学员05','DEMO-202611-SEQUENCE','【演示】2026年11月 顺序控制与过载保护',69.00,'过载','2026-11-07 11:46:18'),(14,'DEMO-006','演示学员06','DEMO-202611-SEQUENCE','【演示】2026年11月 顺序控制与过载保护',76.00,'顺序','2026-11-07 11:46:18'),(15,'DEMO-007','演示学员07','DEMO-202611-SEQUENCE','【演示】2026年11月 顺序控制与过载保护',82.00,'过载','2026-11-07 11:46:18'),(16,'DEMO-008','演示学员08','DEMO-202611-SEQUENCE','【演示】2026年11月 顺序控制与过载保护',63.00,'顺序、过载','2026-11-07 11:46:18');
INSERT INTO exam_result (id,student_no,student_name,test_id,test_name,test_score,created_at) VALUES (17,'20251001','郁同学','DEMO-01','测试·基础接线',62.00,'2026-11-19 16:49:25');
/*!40000 ALTER TABLE `exam_result` ENABLE KEYS */;
UNLOCK TABLES;
INSERT INTO exam_recording (result_id,recording_id,sha256) VALUES (17,'4ff91275465649358c85f2b805bbb211','d244522b676783d63beb499f2d48692994855de62e4e0e2a00f963ba9e2e768c');


--
-- Table structure for table `exam_test`
--

DROP TABLE IF EXISTS `exam_test`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `exam_test` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `test_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '考试名称',
  `test_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '考试题型',
  `duration_minutes` int NOT NULL COMMENT '考试时长（分钟）',
  `publish_time` datetime NOT NULL COMMENT '考试发布时间',
  `deadline_time` datetime NOT NULL COMMENT '考试截止时间',
  `teacher_id` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '发起考试的教师工号',
  `create_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `update_time` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_teacher` (`teacher_id`) USING BTREE,
  KEY `idx_publish_time` (`publish_time`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=12 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='考试信息表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `exam_test`
--

LOCK TABLES `exam_test` WRITE;
/*!40000 ALTER TABLE `exam_test` DISABLE KEYS */;
INSERT INTO `exam_test` VALUES (1,'test_1','电机正反转控制电路',60,'2025-10-15 10:30:00','2025-10-16 10:30:00','2024001','2025-10-15 02:31:08','2025-10-15 02:31:08'),(2,'test_1','电机正反转控制电路',60,'2025-10-15 14:36:00','2025-10-16 14:36:00','20252001','2025-10-15 06:36:42','2025-10-15 06:36:42'),(3,'期中考试','星三角降压启动电路',60,'2025-10-15 16:28:00','2025-10-16 16:28:00','20252001','2025-10-15 08:28:44','2025-10-15 08:28:44'),(4,'多地控制电路','多地控制电路',60,'2026-08-04 10:25:00','2026-08-05 10:25:00','2024001','2026-08-04 02:25:38','2026-08-04 02:25:38'),(5,'26年期末自锁互锁','自锁互锁控制电路',90,'2026-08-05 10:55:00','2026-08-06 10:55:00','20252001','2026-08-05 02:56:28','2026-08-05 02:56:28'),(6,'26/8/6夜晚考试','能耗制动控制电路',180,'2026-08-06 19:48:00','2026-08-07 19:48:00','2024001','2026-08-06 11:49:25','2026-08-06 11:49:25'),(7,'测试1','时间控制电路',60,'2026-08-07 10:13:00','2026-08-21 10:13:00','2024001','2026-08-07 02:13:25','2026-08-07 02:13:25'),(8,'测试2','多地控制电路',60,'2026-08-07 10:13:00','2026-08-20 10:13:00','2024001','2026-08-07 02:13:41','2026-08-07 02:13:41'),(9,'测试3','时间控制电路',99,'2026-08-07 10:18:00','2026-08-28 10:18:00','20252001','2026-08-07 02:18:51','2026-08-07 02:18:51'),(10,'17好的测试','电机正反转控制电路',60,'2026-08-17 15:45:00','2026-08-18 15:45:00','20252001','2026-08-17 07:45:17','2026-08-17 07:45:17'),(11,'收到v','顺序控制电路',60,'2026-09-01 15:38:00','2026-09-02 15:38:00','20252001','2026-09-01 07:38:44','2026-09-01 07:38:44');
/*!40000 ALTER TABLE `exam_test` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `register`
--

DROP TABLE IF EXISTS `register`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `register` (
  `user_id` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `user_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `user_password` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `user_type` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `user_approve` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `register`
--

LOCK TABLES `register` WRITE;
/*!40000 ALTER TABLE `register` DISABLE KEYS */;
INSERT INTO `register` VALUES ('20262004','刘老师','a123456','teacher','20252001'),('20262069','哲同学','a123456','student','20252001'),('20268523','浩同学','a123456','student','20252001'),('20262603','庚同学','a123456','student','20252001');
/*!40000 ALTER TABLE `register` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `reviews`
--

DROP TABLE IF EXISTS `reviews`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `reviews` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL COMMENT '外键关联 users.id',
  `reviewer_id` int NOT NULL COMMENT '审核者ID（通常为教师用户ID）',
  `status` enum('approved','rejected','pedding') CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '审核状态',
  `reason` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '拒绝原因',
  `create_time` datetime NOT NULL COMMENT '申请时间',
  `review_time` datetime NOT NULL COMMENT '审批时间',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `reviews`
--

LOCK TABLES `reviews` WRITE;
/*!40000 ALTER TABLE `reviews` DISABLE KEYS */;
/*!40000 ALTER TABLE `reviews` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `score`
--

DROP TABLE IF EXISTS `score`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `score` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `student_id` int unsigned NOT NULL,
  `test_id` int unsigned NOT NULL,
  `score` int NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  KEY `student_id` (`student_id`) USING BTREE,
  KEY `test_id` (`test_id`) USING BTREE,
  CONSTRAINT `score_ibfk_2` FOREIGN KEY (`test_id`) REFERENCES `test` (`id`) ON DELETE RESTRICT ON UPDATE RESTRICT
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `score`
--

LOCK TABLES `score` WRITE;
/*!40000 ALTER TABLE `score` DISABLE KEYS */;
INSERT INTO `score` VALUES (1,20251001,1,85),(2,20251003,1,92),(3,20251004,1,78),(4,20262026,1,88);
/*!40000 ALTER TABLE `score` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `session_records`
--

DROP TABLE IF EXISTS `session_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `session_records` (
  `id` int NOT NULL AUTO_INCREMENT,
  `session_score` decimal(10,2) DEFAULT '0.00',
  `total_score` decimal(10,2) DEFAULT '0.00',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `session_records`
--

LOCK TABLES `session_records` WRITE;
/*!40000 ALTER TABLE `session_records` DISABLE KEYS */;
/*!40000 ALTER TABLE `session_records` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `student`
--

DROP TABLE IF EXISTS `student`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `student` (
  `sno` int unsigned NOT NULL,
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `user_id` int unsigned NOT NULL AUTO_INCREMENT,
  `student_password` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`sno`) USING BTREE,
  UNIQUE KEY `student_unique` (`user_id`) USING BTREE,
  KEY `sno` (`sno`) USING BTREE,
  CONSTRAINT `student_ibfk_2` FOREIGN KEY (`sno`) REFERENCES `users` (`user_no`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `student_users_FK` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=25 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `student`
--

LOCK TABLES `student` WRITE;
/*!40000 ALTER TABLE `student` DISABLE KEYS */;
INSERT INTO `student` VALUES (20251001,'郁同学',1,'a123456'),(20251003,'陈同学',17,'a123456'),(20251004,'徐同学',16,'a123456'),(20262003,'那同学',20,'a123456'),(20262026,'边同学',18,'a123456'),(20262601,'何同学',21,'a123456'),(20262602,'加同学',22,'123456'),(20262605,'潇同学',23,'123456'),(20262608,'政同学',24,'123456');
/*!40000 ALTER TABLE `student` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `teacher`
--

DROP TABLE IF EXISTS `teacher`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `teacher` (
  `tno` int unsigned NOT NULL,
  `name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `user_id` int unsigned NOT NULL AUTO_INCREMENT,
  `teacher_password` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`tno`) USING BTREE,
  UNIQUE KEY `teacher_unique` (`user_id`) USING BTREE,
  CONSTRAINT `teacher_ibfk_1` FOREIGN KEY (`tno`) REFERENCES `users` (`user_no`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `teacher_users_FK` FOREIGN KEY (`user_id`) REFERENCES `users` (`user_id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `teacher`
--

LOCK TABLES `teacher` WRITE;
/*!40000 ALTER TABLE `teacher` DISABLE KEYS */;
INSERT INTO `teacher` VALUES (20252001,'夏老师',2,'a123456');
/*!40000 ALTER TABLE `teacher` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `test`
--

DROP TABLE IF EXISTS `test`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `test` (
  `id` int unsigned NOT NULL AUTO_INCREMENT,
  `test_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `test_time` datetime NOT NULL,
  `is_testing` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `test`
--

LOCK TABLES `test` WRITE;
/*!40000 ALTER TABLE `test` DISABLE KEYS */;
INSERT INTO `test` VALUES (1,'电路配盘接线','2026-08-06 17:59:36','0');
/*!40000 ALTER TABLE `test` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `users`
--

DROP TABLE IF EXISTS `users`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `users` (
  `user_id` int unsigned NOT NULL AUTO_INCREMENT,
  `user_no` int unsigned NOT NULL,
  `password` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `role` enum('teacher','student') CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (`user_id`) USING BTREE,
  KEY `user_no` (`user_no`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=25 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `users`
--

LOCK TABLES `users` WRITE;
/*!40000 ALTER TABLE `users` DISABLE KEYS */;
INSERT INTO `users` VALUES (1,20251001,'a123456','student'),(2,20252001,'a123456','teacher'),(16,20251004,'a123456','student'),(17,20251003,'a123456','student'),(18,20262026,'a123456','student'),(19,26060060,'123456','student'),(20,20262003,'123456','student'),(21,20262601,'123456','student'),(22,20262602,'123456','student'),(23,20262605,'123456','student'),(24,20262608,'123456','student');
/*!40000 ALTER TABLE `users` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `wiring_history`
--

DROP TABLE IF EXISTS `wiring_history`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `wiring_history` (
  `id` int NOT NULL AUTO_INCREMENT,
  `operation_type` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `pair_data` json DEFAULT NULL,
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `wiring_history`
--

LOCK TABLES `wiring_history` WRITE;
/*!40000 ALTER TABLE `wiring_history` DISABLE KEYS */;
/*!40000 ALTER TABLE `wiring_history` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `wiring_records`
--

DROP TABLE IF EXISTS `wiring_records`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `wiring_records` (
  `id` int NOT NULL AUTO_INCREMENT,
  `end1` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `end2` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `score` decimal(10,2) DEFAULT '0.00',
  `status` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT 'pending',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`) USING BTREE
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `wiring_records`
--

LOCK TABLES `wiring_records` WRITE;
/*!40000 ALTER TABLE `wiring_records` DISABLE KEYS */;
INSERT INTO `wiring_records` VALUES (1,'测试触点A','测试触点B',10.00,'pending','2026-08-03 20:02:13');
/*!40000 ALTER TABLE `wiring_records` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping events for database 'video_project'
--

--
-- Dumping routines for database 'video_project'
--
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

/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-11-13 19:33:12
