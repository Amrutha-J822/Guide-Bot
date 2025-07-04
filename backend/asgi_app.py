import os
import base64
import io
import threading
import time
import re
import asyncio
from dotenv import load_dotenv
import openai
from gtts import gTTS
import socketio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Load environment variables
load_dotenv()
api_key = os.getenv("API_KEY")
if not api_key:
    raise RuntimeError("API_KEY not found in environment. Please add API_KEY=sk-... to your .env file.")

client = openai.OpenAI(api_key=api_key)

FALLBACK_MESSAGE = "I cannot reply to this question. Please ask something related to Indian tourism."
PAUSE_MESSAGE = "Paused. You can ask your next question whenever you're ready."
PROMPT_AFTER_PAUSE = "Please ask me the question, or would you like me to resume my previous response?"

# In-memory state for single user
paused_state = {
    'response_text': None,
    'position': 0,
    'is_paused': False,
    'timer': None
}

current_response_event = threading.Event()
current_response_event.set()  # Initially set so first response can run

def clean_text_for_tts(text):
    # Remove markdown symbols
    text = re.sub(r'[*/_`]', '', text)
    # Replace URLs with site names
    def url_replacer(match):
        url = match.group(0)
        domain = re.findall(r'https?://(?:www\.)?([^/]+)', url)
        if domain:
            return f'Check {domain[0]} for more information'
        return ''
    text = re.sub(r'https?://\S+', url_replacer, text)
    return text

def ensure_english(text):
    translation_prompt = [
        {"role": "system", "content": "Translate the following text to English. If it is already in English, just repeat it."},
        {"role": "user", "content": text}
    ]
    translation_resp = client.chat.completions.create(
        model="gpt-4o",
        messages=translation_prompt,
        stream=False
    )
    return translation_resp.choices[0].message.content

def start_pause_timer(sio, sid):
    def timer_func():
        time.sleep(5)
        if paused_state['is_paused']:
            sio.emit('response_chunk', {'text': PROMPT_AFTER_PAUSE}, to=sid)
            tts = gTTS(text=PROMPT_AFTER_PAUSE, lang='en')
            audio_buffer = io.BytesIO()
            tts.write_to_fp(audio_buffer)
            audio_buffer.seek(0)
            audio_base64 = base64.b64encode(audio_buffer.read()).decode('utf-8')
            sio.emit('audio_response', {'audio': audio_base64}, to=sid)
    paused_state['timer'] = threading.Thread(target=timer_func)
    paused_state['timer'].start()

# Use only the deployed frontend and localhost for CORS
ALLOWED_ORIGINS = [
    "https://guide-bot-6i37.onrender.com",
    "http://localhost:3000"
]

sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=ALLOWED_ORIGINS,
    ping_timeout=60,
    ping_interval=25
)
app = FastAPI()

@sio.event
async def connect(sid, environ):
    print(f"Client connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"Client disconnected: {sid}")

@sio.on('audio_chunk')
async def handle_audio_chunk(sid, data):
    global current_response_event
    print(f"Received audio_chunk from {sid}")
    try:
        if current_response_event.is_set() is False:
            current_response_event.set()
            time.sleep(0.1)
        current_response_event = threading.Event()

        transcript = None
        try:
            audio_data = base64.b64decode(data['audio'])
            audio_file = io.BytesIO(audio_data)
            audio_file.name = "audio.wav"
            print("Transcribing audio...")
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            )
            transcript = transcription.text.strip()
            print(f"Transcript: {transcript}")
        except Exception as e:
            print("Error in transcription:", e)
            transcript = None

        if not transcript or transcript.strip() == "":
            print("Transcript is empty or None. Sending fallback.")
            await sio.emit('response_chunk', {'text': FALLBACK_MESSAGE}, to=sid)
            tts = gTTS(text=FALLBACK_MESSAGE, lang='en')
            buf = io.BytesIO()
            tts.write_to_fp(buf)
            buf.seek(0)
            audio_b64 = base64.b64encode(buf.read()).decode('utf-8')
            await sio.emit('audio_response', {'audio': audio_b64}, to=sid)
            current_response_event.set()
            return
        else:
            print(f"Transcript sent to LLM: {transcript}")

        system_prompt = (
            "You are an expert on Indian tourism. "
            "Always answer questions about any place, city, monument, landmark, food, culture, or history in India as Indian tourism. "
            "For example, if the user asks about the Taj Mahal, Qutub Minar, Jaipur, Varanasi, Indian food, or any Indian city, treat it as a tourism question. "
            "If the question is not about India or Indian tourism, reply exactly: 'I cannot reply to this question. Please ask something related to Indian tourism.'"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": transcript}
        ]

        response_text = ""
        def stream_llm_and_tts():
            nonlocal response_text
            try:
                print("Streaming LLM response...")
                stream = client.chat.completions.create(
                    model="gpt-4o",
                    messages=messages,
                    stream=True
                )
                for chunk in stream:
                    if current_response_event.is_set():
                        break
                    delta = chunk.choices[0].delta.content if chunk.choices[0].delta else None
                    if delta:
                        response_text += delta
                        asyncio.run(sio.emit('response_chunk', {'text': delta}, to=sid))
                print(f"LLM response: {response_text}")
                if response_text and not current_response_event.is_set():
                    print(f"Final LLM response: {response_text}")
                    tts_text = clean_text_for_tts(response_text)
                    tts = gTTS(text=tts_text, lang='en')
                    buf = io.BytesIO()
                    tts.write_to_fp(buf)
                    buf.seek(0)
                    audio_b64 = base64.b64encode(buf.read()).decode('utf-8')
                    asyncio.run(sio.emit('audio_response', {'audio': audio_b64}, to=sid))
            except Exception as e:
                print("Error in stream_llm_and_tts:", e)
                # Always send fallback message/audio if LLM or TTS fails
                asyncio.run(sio.emit('response_chunk', {'text': FALLBACK_MESSAGE}, to=sid))
                tts = gTTS(text=FALLBACK_MESSAGE, lang='en')
                buf = io.BytesIO()
                tts.write_to_fp(buf)
                buf.seek(0)
                audio_b64 = base64.b64encode(buf.read()).decode('utf-8')
                asyncio.run(sio.emit('audio_response', {'audio': audio_b64}, to=sid))
            finally:
                current_response_event.set()
        t = threading.Thread(target=stream_llm_and_tts)
        t.start()
        t.join()
        paused_state['response_text'] = response_text
        paused_state['position'] = 0
    except Exception as e:
        import traceback
        print("Error in handle_audio_chunk:")
        traceback.print_exc()
        # Always send fallback message/audio if something else fails
        await sio.emit('response_chunk', {'text': FALLBACK_MESSAGE}, to=sid)
        tts = gTTS(text=FALLBACK_MESSAGE, lang='en')
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        audio_b64 = base64.b64encode(buf.read()).decode('utf-8')
        await sio.emit('audio_response', {'audio': audio_b64}, to=sid)
        current_response_event.set()

@sio.on('pause')
async def handle_pause(sid):
    print(f"Pause requested by {sid}")
    paused_state['is_paused'] = True
    # The current response_text and position should already be tracked during streaming
    await sio.emit('response_chunk', {'text': PAUSE_MESSAGE}, to=sid)

@sio.on('resume')
async def handle_resume(sid):
    print(f"Resume requested by {sid}")
    if paused_state['is_paused'] and paused_state['response_text']:
        paused_state['is_paused'] = False
        # Resume streaming from the last paused position
        response_text = paused_state['response_text']
        position = paused_state['position']
        remaining_text = response_text[position:]
        chunk_size = 100  # Adjust as needed for streaming granularity
        while position < len(response_text):
            if paused_state['is_paused']:
                break
            chunk = response_text[position:position+chunk_size]
            await sio.emit('response_chunk', {'text': chunk}, to=sid)
            position += chunk_size
            paused_state['position'] = position
            await asyncio.sleep(0.1)  # Simulate streaming delay
        # After finishing, send TTS audio again for the remaining text
        tts_text = clean_text_for_tts(remaining_text)
        tts = gTTS(text=tts_text, lang='en')
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        audio_b64 = base64.b64encode(buf.read()).decode('utf-8')
        await sio.emit('audio_response', {'audio': audio_b64}, to=sid)
        paused_state['response_text'] = None
        paused_state['position'] = 0

# Mount Socket.IO ASGI app onto FastAPI
app.mount("/socket.io", socketio.ASGIApp(sio, socketio_path="/socket.io"))

# Serve React static files from frontend/build
app.mount(
    "/",
    StaticFiles(directory=os.path.join(os.path.dirname(__file__), "../frontend/build"), html=True),
    name="static"
)

@app.get("/")
def root():
    return {"message": "Server is running! (FastAPI + Socket.IO)"}

@app.get("/test")
def test():
    return {"status": "ok"}

@app.get("/test-openai")
def test_openai():
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Hello"}],
            stream=False
        )
        return {"result": resp.choices[0].message.content}
    except Exception as e:
        import traceback
        return {"error": str(e)} 