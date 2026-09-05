#!/bin/bash
# Run the FastAPI development server with source reload enabled.
uvicorn app.main:app --reload --host 0.0.0.0