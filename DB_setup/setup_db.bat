:: setup_db.bat

@echo off
echo 🚀 Starting MongoDB Setup...

:: Change this to your MongoDB bin path if mongosh isn't in PATH
SET MONGO_PATH="C:\Program Files\mongosh\bin\mongosh.exe"

:: Run the db setup JS file
%MONGO_PATH% < db_setup.js

echo ✅ MongoDB Setup Complete!
pause
