-- Local only: creates one database and one login per service in the compose SQL Server.
-- Run by the one-off `db-init` compose service with sqlcmd, which fills in $(PERSONAL_DB_PASSWORD)
-- and $(HOUSEHOLDS_DB_PASSWORD) from its environment. Safe to run on every `docker compose up`:
-- each step checks first, and the passwords are re-applied so they always match .env.
-- On Azure the same users are created once by hand as contained users (see plan.md §11).
:on error exit

IF DB_ID(N'personal') IS NULL CREATE DATABASE personal;
GO
IF DB_ID(N'households') IS NULL CREATE DATABASE households;
GO

-- Server logins. Neither login gets a server role, so each one can only open the database
-- where it has a user (guest access is off in user databases).
IF NOT EXISTS (SELECT 1 FROM sys.sql_logins WHERE name = N'personal_svc')
    CREATE LOGIN personal_svc WITH PASSWORD = N'$(PERSONAL_DB_PASSWORD)', DEFAULT_DATABASE = personal;
ELSE
    ALTER LOGIN personal_svc WITH PASSWORD = N'$(PERSONAL_DB_PASSWORD)';
GO
IF NOT EXISTS (SELECT 1 FROM sys.sql_logins WHERE name = N'households_svc')
    CREATE LOGIN households_svc WITH PASSWORD = N'$(HOUSEHOLDS_DB_PASSWORD)', DEFAULT_DATABASE = households;
ELSE
    ALTER LOGIN households_svc WITH PASSWORD = N'$(HOUSEHOLDS_DB_PASSWORD)';
GO

-- In each database: a user for its own login only, with the three roles the service needs to run
-- its migrations (db_ddladmin) and read and write its data. Not db_owner.
USE personal;
IF USER_ID(N'personal_svc') IS NULL CREATE USER personal_svc FOR LOGIN personal_svc;
IF IS_ROLEMEMBER(N'db_ddladmin', N'personal_svc') = 0 ALTER ROLE db_ddladmin ADD MEMBER personal_svc;
IF IS_ROLEMEMBER(N'db_datareader', N'personal_svc') = 0 ALTER ROLE db_datareader ADD MEMBER personal_svc;
IF IS_ROLEMEMBER(N'db_datawriter', N'personal_svc') = 0 ALTER ROLE db_datawriter ADD MEMBER personal_svc;
GO

USE households;
IF USER_ID(N'households_svc') IS NULL CREATE USER households_svc FOR LOGIN households_svc;
IF IS_ROLEMEMBER(N'db_ddladmin', N'households_svc') = 0 ALTER ROLE db_ddladmin ADD MEMBER households_svc;
IF IS_ROLEMEMBER(N'db_datareader', N'households_svc') = 0 ALTER ROLE db_datareader ADD MEMBER households_svc;
IF IS_ROLEMEMBER(N'db_datawriter', N'households_svc') = 0 ALTER ROLE db_datawriter ADD MEMBER households_svc;
GO

PRINT 'db-init: databases personal and households and their logins are ready';
