# Guide-Bot🤖

A hands-free, conversational AI assistant for exploring Indian tourism. Speak your questions, no buttons needed and get instant, spoken, and written answers.
---
## Demo
<video src="assets\Guide-Bot.mp4" controls width="600">
  Your browser does not support the video tag.
</video>
---

## Table of Contents
1. [Features](#features)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
   - [Backend Setup](#backend-setup)
   - [Frontend Setup](#frontend-setup)
4. [Usage](#usage)
5. [Configuration](#configuration)
6. [Deployment](#deployment)
7. [Architecture](#architecture)
8. [Customization & Extensibility](#customization--extensibility)
9. [Troubleshooting](#troubleshooting)
10. [License](#license)
11. [Credits](#credits)

---
## Architecture

```
User Mic → Frontend (SpeechRecognition + MediaRecorder)
                       ↓
               WebSocket (socket.io)
                       ↓
                 Backend (FastAPI)
      Whisper → GPT-4o → gTTS (TTS) → Response
```

---

## Features
- **Hands-free interaction**: Speak to ask questions about Indian cities, monuments, cuisine, culture, and more.
- **Silence detection**: Automatically stops recording when you finish speaking.
- **Pause/Stop commands**: Say "pause" or "stop" anytime to interrupt the response.
- **Real-time streaming**: Partial answers appear instantly; full text and audio delivered seamlessly.
- **5-second fallback**: If TTS fails or takes too long, text is still displayed.
- **Automatic resume**: Bot listens for your next query right after replying.

---

## Prerequisites
- **Node.js** (>=14.x)
- **Python** (>=3.8)
- **pip** for installing Python packages
- **OpenAI API Key** (`API_KEY`)
- Optional: **Pinecone** for memory and search (`PINE_CONE_DB`, `PINECONE_ENV`)

---

## Installation

### Backend Setup

1. Navigate to the backend folder:
   ```sh
   cd guide_ai/backend
   
2. Create a `.env` file and add your keys:

   ```ini
   API_KEY=sk-...
   # (Optional) Pinecone keys:
   PINE_CONE_DB=...
   PINECONE_ENV=...
   ```
3. Install dependencies:

   ```sh
   pip install -r requirements.txt
   ```
4. Start the server:

   ```sh
   uvicorn asgi_app:app --host 0.0.0.0 --port 5000
   ```

### Frontend Setup

1. From the project root, navigate to the frontend:

   ```sh
   cd guide_ai/frontend
   ```
2. Create a `.env` in this folder (if needed) and set:

   ```ini
   REACT_APP_API_URL=http://localhost:5000
   ```
3. Install dependencies:

   ```sh
   npm install
   ```
4. Start the React app:

   ```sh
   npm start
   ```

* **Frontend**: [http://localhost:3000](http://localhost:3000)
* **Backend**:  [http://localhost:5000](http://localhost:5000)

---

## Usage

1. **Open** the frontend in your browser.
2. Click **Start Listening** or simply start speaking.
3. Ask about any Indian tourist spot or topic.
4. Bot answers both **in text** and **audio**.
5. Say **pause** or click **Stop Chatting** anytime to interrupt.

---

## Configuration

* Adjust **silence sensitivity** in `App.tsx`:

  ```ts
  const SILENCE_THRESHOLD = 0.01;
  const SILENCE_DURATION  = 1000; // in ms
  ```
* Change **voice-activity** threshold:

  ```ts
  const VOICE_THRESHOLD = 0.015;
  ```
* Backend TTS settings in `asgi_app.py`:

  ```python
  from gtts import gTTS
  ```

---

## Deployment

* **Frontend**: Vercel or Netlify
* **Backend**: Render.com, Railway, or self-host on a VPS
* Set environment variables in your deployment platform to match `.env`.

---

## Customization & Extensibility

* **Pinecone integration**: for long-term memory or retrieval-augmented generation.
* **LLM fine-tuning**: tailor GPT model prompts for niche domains.
* **Authentication**: add user accounts for personalized experiences.
* **Multilingual support**: extend Web Speech API and gTTS to other languages.

---

## Troubleshooting

* **No audio**: ensure microphone permissions granted.
* **Playback fails**: check browser support for MP3 and CORS on backend.
* **Connection errors**: verify backend is running and `REACT_APP_API_URL` is correct.

---

## License

This project is licensed under the MIT License.

---

## Credits

* [OpenAI](https://openai.com)
* [FastAPI](https://fastapi.tiangolo.com)
* [Socket.IO](https://socket.io)
* [gTTS](https://pypi.org/project/gTTS)
* [React](https://react.dev)

```
```
