#!/bin/bash

set -e  # Exit on error

echo "=================================================="
echo "  Airport Performance Analyzer – Setup Database"
echo "=================================================="
echo ""

# --- User input ---
read -p "PostgreSQL username:  " DB_USER
read -s -p "PostgreSQL password:  " DB_PASSWORD
echo ""
read -p "Database name:        " DB_NAME
echo ""

# --- Step 2: Create user and database ---
echo ">> Creating database user '$DB_USER'..."
sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';"

echo ">> Creating database '$DB_NAME'..."
sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"

# --- Step 3: Load schema and grant permissions ---
echo ">> Loading schema and granting permissions..."
sudo -u postgres psql -d "$DB_NAME" -v app_user="$DB_USER" -f database/setup.sql

sudo -u postgres psql -d "$DB_NAME" -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $DB_USER;"
sudo -u postgres psql -d "$DB_NAME" -c "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO $DB_USER;"

# --- Step 4: Create .env file ---
echo ">> Creating .env file..."
cat > scripts/import/.env <<EOF
DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME
EOF
echo "   .env created at scripts/import/.env"

echo ">> Copying .env file..."
cp scrips/import/.env  notebooks/
echo "   .env created at notebooks/.env"

# --- Step 5: Install Python dependencies ---
echo ">> Setting up Python virtual environment..."
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

echo ""
echo "=================================================="
echo "  Setup completed!"
echo "=================================================="
