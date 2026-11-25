-- 003: a saved member name now records when personal last gave it, and only names that personal
-- actually returned are kept. This corrects 002, whose backfill stored the "Member #id" fallback as if
-- it were a name (applied migrations are never edited, so the correction is a new file). Runs against
-- memberships that already hold data: every row is kept, only member_name and the new column change.
ALTER TABLE memberships ADD member_name_saved_at DATETIME2(0) NULL;
GO
-- The fallback is computed when a page is built, so a stored copy of it says nothing. BIN2: exact text.
UPDATE memberships SET member_name = NULL
WHERE member_name COLLATE Latin1_General_BIN2 = CONCAT(N'Member #', user_id);
GO
-- Names already saved came from personal; the moment they were saved was not recorded, so the
-- migration time stands in for it.
UPDATE memberships SET member_name_saved_at = SYSUTCDATETIME()
WHERE member_name IS NOT NULL AND member_name_saved_at IS NULL;
