#!/bin/bash
git pull
sudo docker compose build --no-cache backend frontend
sudo docker compose up -d
docker compose exec backend alembic upgrade head
sudo docker compose restart backend
sudo docker compose restart frontend
