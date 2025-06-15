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

# Use only the React frontend origin for CORS
FRONTEND_ORIGIN = "http://localhost:3000"

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins=[FRONTEND_ORIGIN])
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

        # Stronger, more explicit system prompt
        system_prompt = (
            "You are an expert on Indian tourism. "
            "Always answer questions about any place, city, monument, landmark, food, culture, or history in India as Indian tourism. "
            "For example, if the user asks about the Taj Mahal, Qutub Minar, Jaipur, Varanasi, Indian food, or any Indian city, treat it as a tourism question. "
            "If the question is not about India or Indian tourism, reply exactly: 'I cannot reply to this question. Please ask something related to Indian tourism.'"
        )
        messages = [
            {
                "role": "system",
                "content": system_prompt
            }
        ]
        if paused_state['is_paused']:
            previous_context = paused_state['response_text'] or ""
            paused_state['is_paused'] = False
            paused_state['response_text'] = None
            paused_state['position'] = 0
        else:
            previous_context = None
        if previous_context:
            messages.append({"role": "assistant", "content": previous_context})
        messages.append({"role": "user", "content": transcript})

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
                
                # Stream text chunks
                for chunk in stream:
                    if current_response_event.is_set():
                        break
                    delta = chunk.choices[0].delta.content if chunk.choices[0].delta else None
                    if delta:
                        response_text += delta
                        asyncio.run(sio.emit('response_chunk', {'text': delta}, to=sid))
                
                # Only generate and send audio if we have a complete response
                if response_text and not current_response_event.is_set():
                    print(f"Final LLM response: {response_text}")
                    # Clean text for TTS
                    tts_text = clean_text_for_tts(response_text)
                    # Generate TTS
                    tts = gTTS(text=tts_text, lang='en')
                    buf = io.BytesIO()
                    tts.write_to_fp(buf)
                    buf.seek(0)
                    audio_b64 = base64.b64encode(buf.read()).decode('utf-8')
                    # Send final audio
                    asyncio.run(sio.emit('audio_response', {'audio': audio_b64}, to=sid))
                
            except Exception as e:
                print(f"Error in stream_llm_and_tts: {e}")
                asyncio.run(sio.emit('error', {'message': str(e)}, to=sid))
            finally:
                current_response_event.set()
        t = threading.Thread(target=stream_llm_and_tts)
        t.start()
        t.join()
        paused_state['response_text'] = response_text
        paused_state['position'] = 0
    except Exception as e:
        print(f"Error in handle_audio_chunk: {e}")
        await sio.emit('error', {'message': str(e)}, to=sid)

# Mount Socket.IO ASGI app onto FastAPI
app.mount("/socket.io", socketio.ASGIApp(sio, socketio_path="/socket.io"))

@app.get("/")
def root():
    return {"message": "Server is running! (FastAPI + Socket.IO)"} 