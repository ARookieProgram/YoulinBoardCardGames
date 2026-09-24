-- ============================================================================
-- 幼麟麻将 · 管理平台数据库（db_scmj_admin）
-- ============================================================================
--
-- 本文件由 Django 的迁移自动生成，**不要手工编辑**。
--   生成命令：cd server-python/platform_server && ../.venv/bin/python scripts/gen_sql.py \
--               --output sql/db_scmj_admin.sql
--   自检命令：../.venv/bin/python manage.py test tests.test_sql_script
--
-- 权威定义是 Django 的迁移文件（apps/*/migrations/）：
-- 改了模型 → `makemigrations` → 重新生成本文件 → 一起提交。
--
-- ⚠️ 这是"初始建库"脚本，等价于在**空库**上跑一次 `migrate`。
--    已有数据的库升级请用 `manage.py migrate`，不要重跑本文件
--    （Django 靠 django_migrations 表判断哪些迁移已应用，重跑会撞表）。
--
-- 内容分三部分：
--   1. 建库语句；
--   2. 逐条迁移的真实执行 SQL（与 `migrate` 实际执行的语句一致，
--      因此会有"建完又改"的中转语句，例如 token_blacklist 的 jti 列）；
--   3. 最终 schema 速查（只是注释，方便阅读，不执行）。
--
-- 与玩家库 `db_scmj` 隔离：本库只放管理平台的账号与登录态，
-- 不含 t_accounts / t_users 等玩家表。玩家数据由平台通过**只读数据源**
-- （Django 的 DATABASES['player']，只执行 SELECT）读取，不落在本库。
-- 玩家封禁记录是本平台的表（players_playerban），同理不落到玩家库。
--
-- 目标：MySQL 8.0+ / utf8mb4
-- ============================================================================

-- 建库（已存在时跳过）。字符集必须 utf8mb4：管理员昵称、备注可能是四字节字符。
CREATE DATABASE IF NOT EXISTS `db_scmj_admin`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `db_scmj_admin`;

-- 建表期间不校验外键，避免因表的创建顺序导致失败（与原 db_babykylin.sql 同一手法）。
SET FOREIGN_KEY_CHECKS=0;

  contenttypes.0001_initial
CREATE TABLE `django_content_type` (`id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY, `name` varchar(100) NOT NULL, `app_label` varchar(100) NOT NULL, `model` varchar(100) NOT NULL);
ALTER TABLE `django_content_type` ADD CONSTRAINT `django_content_type_app_label_model_76bd3d3b_uniq` UNIQUE (`app_label`, `model`);
  contenttypes.0002_remove_content_type_name
ALTER TABLE `django_content_type` MODIFY `name` varchar(100) NULL;
ALTER TABLE `django_content_type` DROP COLUMN `name`;
  auth.0001_initial
CREATE TABLE `auth_permission` (`id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY, `name` varchar(50) NOT NULL, `content_type_id` integer NOT NULL, `codename` varchar(100) NOT NULL);
CREATE TABLE `auth_group` (`id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY, `name` varchar(80) NOT NULL UNIQUE);
CREATE TABLE `auth_group_permissions` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `group_id` integer NOT NULL, `permission_id` integer NOT NULL);
ALTER TABLE `auth_permission` ADD CONSTRAINT `auth_permission_content_type_id_codename_01ab375a_uniq` UNIQUE (`content_type_id`, `codename`);
ALTER TABLE `auth_permission` ADD CONSTRAINT `auth_permission_content_type_id_2f476e4b_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`);
ALTER TABLE `auth_group_permissions` ADD CONSTRAINT `auth_group_permissions_group_id_permission_id_0cd325b0_uniq` UNIQUE (`group_id`, `permission_id`);
ALTER TABLE `auth_group_permissions` ADD CONSTRAINT `auth_group_permissions_group_id_b120cbf9_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`);
ALTER TABLE `auth_group_permissions` ADD CONSTRAINT `auth_group_permissio_permission_id_84c5c92e_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`);
  auth.0002_alter_permission_name_max_length
ALTER TABLE `auth_permission` MODIFY `name` varchar(255) NOT NULL;
  auth.0003_alter_user_email_max_length

  auth.0004_alter_user_username_opts

  auth.0005_alter_user_last_login_null

  auth.0006_require_contenttypes_0002

  auth.0007_alter_validators_add_error_messages

  auth.0008_alter_user_username_max_length

  auth.0009_alter_user_last_name_max_length

  auth.0010_alter_group_name_max_length
ALTER TABLE `auth_group` MODIFY `name` varchar(150) NOT NULL;
  auth.0011_update_proxy_permissions

  auth.0012_alter_user_first_name_max_length

  accounts.0001_initial
CREATE TABLE `accounts_adminuser` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `password` varchar(128) NOT NULL, `last_login` datetime(6) NULL, `is_superuser` bool NOT NULL, `username` varchar(150) NOT NULL UNIQUE, `first_name` varchar(150) NOT NULL, `last_name` varchar(150) NOT NULL, `is_staff` bool NOT NULL, `is_active` bool NOT NULL, `date_joined` datetime(6) NOT NULL, `nickname` varchar(32) NOT NULL, `email` varchar(254) NOT NULL UNIQUE, `role` varchar(20) NOT NULL, `status` varchar(20) NOT NULL, `remark` varchar(200) NOT NULL, `last_login_ip` char(39) NULL, `created_at` datetime(6) NOT NULL, `updated_at` datetime(6) NOT NULL);
CREATE TABLE `accounts_adminuser_groups` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `adminuser_id` bigint NOT NULL, `group_id` integer NOT NULL);
CREATE TABLE `accounts_adminuser_user_permissions` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `adminuser_id` bigint NOT NULL, `permission_id` integer NOT NULL);
CREATE INDEX `accounts_adminuser_role_a169e5ed` ON `accounts_adminuser` (`role`);
CREATE INDEX `accounts_adminuser_status_3ad623eb` ON `accounts_adminuser` (`status`);
CREATE INDEX `idx_admin_role_status` ON `accounts_adminuser` (`role`, `status`);
ALTER TABLE `accounts_adminuser_groups` ADD CONSTRAINT `accounts_adminuser_groups_adminuser_id_group_id_9ada8b9a_uniq` UNIQUE (`adminuser_id`, `group_id`);
ALTER TABLE `accounts_adminuser_groups` ADD CONSTRAINT `accounts_adminuser_g_adminuser_id_d27820d1_fk_accounts_` FOREIGN KEY (`adminuser_id`) REFERENCES `accounts_adminuser` (`id`);
ALTER TABLE `accounts_adminuser_groups` ADD CONSTRAINT `accounts_adminuser_groups_group_id_fa364085_fk_auth_group_id` FOREIGN KEY (`group_id`) REFERENCES `auth_group` (`id`);
ALTER TABLE `accounts_adminuser_user_permissions` ADD CONSTRAINT `accounts_adminuser_user__adminuser_id_permission__0e9ac9f4_uniq` UNIQUE (`adminuser_id`, `permission_id`);
ALTER TABLE `accounts_adminuser_user_permissions` ADD CONSTRAINT `accounts_adminuser_u_adminuser_id_5ee267b3_fk_accounts_` FOREIGN KEY (`adminuser_id`) REFERENCES `accounts_adminuser` (`id`);
ALTER TABLE `accounts_adminuser_user_permissions` ADD CONSTRAINT `accounts_adminuser_u_permission_id_c848505f_fk_auth_perm` FOREIGN KEY (`permission_id`) REFERENCES `auth_permission` (`id`);
  admin.0001_initial
CREATE TABLE `django_admin_log` (`id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY, `action_time` datetime(6) NOT NULL, `object_id` longtext NULL, `object_repr` varchar(200) NOT NULL, `action_flag` smallint UNSIGNED NOT NULL CHECK (`action_flag` >= 0), `change_message` longtext NOT NULL, `content_type_id` integer NULL, `user_id` bigint NOT NULL);
ALTER TABLE `django_admin_log` ADD CONSTRAINT `django_admin_log_content_type_id_c4bce8eb_fk_django_co` FOREIGN KEY (`content_type_id`) REFERENCES `django_content_type` (`id`);
ALTER TABLE `django_admin_log` ADD CONSTRAINT `django_admin_log_user_id_c564eba6_fk_accounts_adminuser_id` FOREIGN KEY (`user_id`) REFERENCES `accounts_adminuser` (`id`);
  admin.0002_logentry_remove_auto_add

  admin.0003_logentry_add_action_flag_choices

  players.0001_initial
CREATE TABLE `players_playerban` (`id` bigint AUTO_INCREMENT NOT NULL PRIMARY KEY, `player_id` integer UNSIGNED NOT NULL CHECK (`player_id` >= 0), `account` varchar(64) NOT NULL, `player_name` varchar(64) NOT NULL, `action` varchar(16) NOT NULL, `reason` varchar(200) NOT NULL, `operator_name` varchar(150) NOT NULL, `expires_at` datetime(6) NULL, `created_at` datetime(6) NOT NULL, `operator_id` bigint NULL);
ALTER TABLE `players_playerban` ADD CONSTRAINT `players_playerban_operator_id_56a0a605_fk_accounts_adminuser_id` FOREIGN KEY (`operator_id`) REFERENCES `accounts_adminuser` (`id`);
CREATE INDEX `players_playerban_player_id_ff9b4afa` ON `players_playerban` (`player_id`);
CREATE INDEX `idx_player_ban_time` ON `players_playerban` (`player_id`, `created_at` DESC);
CREATE INDEX `idx_player_ban_action` ON `players_playerban` (`action`, `created_at` DESC);
  sessions.0001_initial
CREATE TABLE `django_session` (`session_key` varchar(40) NOT NULL PRIMARY KEY, `session_data` longtext NOT NULL, `expire_date` datetime(6) NOT NULL);
CREATE INDEX `django_session_expire_date_a5c62663` ON `django_session` (`expire_date`);
  token_blacklist.0001_initial
CREATE TABLE `token_blacklist_blacklistedtoken` (`id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY, `blacklisted_at` datetime(6) NOT NULL);
CREATE TABLE `token_blacklist_outstandingtoken` (`id` integer AUTO_INCREMENT NOT NULL PRIMARY KEY, `jti` char(32) NOT NULL UNIQUE, `token` longtext NOT NULL, `created_at` datetime(6) NOT NULL, `expires_at` datetime(6) NOT NULL, `user_id` bigint NOT NULL);
ALTER TABLE `token_blacklist_blacklistedtoken` ADD COLUMN `token_id` integer NOT NULL UNIQUE , ADD CONSTRAINT `token_blacklist_blac_token_id_3cc7fe56_fk_token_bla` FOREIGN KEY (`token_id`) REFERENCES `token_blacklist_outstandingtoken`(`id`);
ALTER TABLE `token_blacklist_outstandingtoken` ADD CONSTRAINT `token_blacklist_outs_user_id_83bc629a_fk_accounts_` FOREIGN KEY (`user_id`) REFERENCES `accounts_adminuser` (`id`);
  token_blacklist.0002_outstandingtoken_jti_hex
ALTER TABLE `token_blacklist_outstandingtoken` ADD COLUMN `jti_hex` varchar(255) NULL;
  token_blacklist.0003_auto_20171017_2007

  token_blacklist.0004_auto_20171017_2013
ALTER TABLE `token_blacklist_outstandingtoken` MODIFY `jti_hex` varchar(255) NOT NULL;
ALTER TABLE `token_blacklist_outstandingtoken` ADD CONSTRAINT `token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_uniq` UNIQUE (`jti_hex`);
  token_blacklist.0005_remove_outstandingtoken_jti
ALTER TABLE `token_blacklist_outstandingtoken` DROP COLUMN `jti`;
  token_blacklist.0006_auto_20171017_2113
ALTER TABLE `token_blacklist_outstandingtoken` RENAME COLUMN `jti_hex` TO `jti`;
  token_blacklist.0007_auto_20171017_2214
ALTER TABLE `token_blacklist_outstandingtoken` MODIFY `created_at` datetime(6) NULL;
ALTER TABLE `token_blacklist_outstandingtoken` MODIFY `user_id` bigint NULL;
  token_blacklist.0008_migrate_to_bigautofield
ALTER TABLE `token_blacklist_blacklistedtoken` MODIFY `id` bigint AUTO_INCREMENT NOT NULL;
ALTER TABLE `token_blacklist_outstandingtoken` MODIFY `id` bigint AUTO_INCREMENT NOT NULL;
ALTER TABLE `token_blacklist_blacklistedtoken` MODIFY `token_id` bigint NOT NULL;
ALTER TABLE `token_blacklist_blacklistedtoken` ADD CONSTRAINT `token_blacklist_blacklistedtoken_token_id_3cc7fe56_fk` FOREIGN KEY (`token_id`) REFERENCES `token_blacklist_outstandingtoken` (`id`);
  token_blacklist.0010_fix_migrate_to_bigautofield

  token_blacklist.0011_linearizes_history

  token_blacklist.0012_alter_outstandingtoken_user

  token_blacklist.0013_alter_blacklistedtoken_options_and_more


SET FOREIGN_KEY_CHECKS=1;

-- ============================================================================
-- 最终 schema 速查（注释，仅供阅读；实际结构以上面的 DDL 为准）
-- ============================================================================

-- 表：`accounts_adminuser`（管理员）
-- 字段：
--   id                           BigAutoField  [主键, 唯一]
--   password                     CharField
--   last_login                   DateTimeField  [可空]
--   is_superuser                 BooleanField
--   username                     CharField  [唯一]
--   first_name                   CharField
--   last_name                    CharField
--   is_staff                     BooleanField
--   is_active                    BooleanField
--   date_joined                  DateTimeField
--   nickname                     CharField
--   email                        CharField  [唯一]
--   role                         CharField  [索引]
--   status                       CharField  [索引]
--   remark                       CharField
--   last_login_ip                GenericIPAddressField  [可空]
--   created_at                   DateTimeField
--   updated_at                   DateTimeField
-- 组合索引：
--   idx_admin_role_status        (role, status)

-- 表：`players_playerban`（玩家封禁记录）
-- 字段：
--   id                           BigAutoField  [主键, 唯一]
--   player_id                    PositiveIntegerField  [索引]
--   account                      CharField
--   player_name                  CharField
--   action                       CharField
--   reason                       CharField
--   operator_id / → accounts_adminuser ForeignKey  [索引, 可空]
--   operator_name                CharField
--   expires_at                   DateTimeField  [可空]
--   created_at                   DateTimeField
-- 组合索引：
--   idx_player_ban_time          (player_id, -created_at)
--   idx_player_ban_action        (action, -created_at)

-- ============================================================================
-- 完成。
--
-- 建完还需要一个能登录的超级管理员——SQL 里不含口令（口令是 PBKDF2 哈希，
-- 必须在应用层生成），所以请接着执行：
--
--   cd server-python/platform_server
--   ../.venv/bin/python manage.py seed_admin --username admin
-- ============================================================================
