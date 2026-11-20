-- 002: keep the last name personal gave us for each member, so household pages show real names
-- while personal is down (ADR-6, plan D5). Runs against tables that already hold data:
-- the column is added as NULL, then every existing membership gets the fallback name the
-- pages already showed. Nothing is dropped or rewritten, and the next successful read
-- replaces the fallback with the real name.
ALTER TABLE memberships ADD member_name NVARCHAR(80) NULL;
GO
UPDATE memberships SET member_name = CONCAT(N'Member #', user_id) WHERE member_name IS NULL;
