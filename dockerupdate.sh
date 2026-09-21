#!/bin/bash
git pull
sudo docker compose build --no-cache backend frontend
sudo docker compose up -d backend frontend
sudo docker compose exec backend alembic upgrade head
