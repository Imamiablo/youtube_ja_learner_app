# YouTube Japanese Learner App

A local-first web app for learning Japanese from YouTube videos.

The app is designed to help learners turn Japanese YouTube transcripts into study material with translations, furigana text, vocabulary extraction, and LLM-assisted explanations.
Any video with subtitles in Japanese can essentially be converted into a useful visual aid material.

## Features

- Import Japanese transcript segments from YouTube videos
- Store study articles in a local SQLite database
- Generate translations with an OpenAI-compatible API
- Support local LLMs through Ollama
- Prepare Japanese text for furigana/ruby display
- Extract vocabulary from transcript segments
- Web interface powered by FastAPI and Jinja2

## Tech stack

- Python
- FastAPI
- Uvicorn
- Jinja2
- SQLite
- youtube-transcript-api
- fugashi
- unidic-lite
- OpenAI-compatible LLM API
- Ollama support

## Installation

Clone the repository:

```bash
git clone https://github.com/Imamiablo/youtube_ja_learner_app.git
cd youtube_ja_learner_app