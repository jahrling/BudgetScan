#!/bin/bash
git pull
sudo docker compose build --no-cache backend frontend
sudo docker compose up -d
sudo docker compose restart backend
