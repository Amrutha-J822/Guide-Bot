import React, { useState, useEffect, useRef, useCallback } from 'react';
import io, { Socket } from 'socket.io-client';
import './App.css';

declare const process: { env: { NODE_ENV: string } };

// Add Web Speech API type declarations
interface SpeechRecognition extends EventTarget {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: (event: SpeechRecognitionEvent) => void;
  onerror: (event: SpeechRecognitionErrorEvent) => void;
  onend: () => void;
  start: () => void;
  stop: () => void;
  abort: () => void;
}

declare global {
  interface Window {
    SpeechRecognition: new () => SpeechRecognition;
    webkitSpeechRecognition: new () => SpeechRecognition;
  }
}

interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList;
  resultIndex: number;
}

interface SpeechRecognitionErrorEvent extends Event {
  error: string;
  message: string;
}

interface SpeechRecognitionResultList {
  length: number;
  item(index: number): SpeechRecognitionResult;
  [index: number]: SpeechRecognitionResult;
}

interface SpeechRecognitionResult {
  isFinal: boolean;
  length: number;
  item(index: number): SpeechRecognitionAlternative;
  [index: number]: SpeechRecognitionAlternative;
}

interface SpeechRecognitionAlternative {
  transcript: string;
  confidence: number;
}

const SILENCE_THRESHOLD = 0.01; // Adjust as needed
const SILENCE_DURATION = 1000; // ms
const VOICE_THRESHOLD = 0.015; // Threshold for voice activity detection

const App: React.FC = () => {
  const [isListening, setIsListening] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [messages, setMessages] = useState<string[]>([]);
  const [hasVoiceActivity, setHasVoiceActivity] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [connectionError, setConnectionError] = useState(false);
  const socketRef = useRef<Socket | null>(null);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const voiceActivityTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const botResponseBuffer = useRef<string>('');
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const recognitionRestartTimeout = useRef<number | null>(null);
  const lastTTSRef = useRef<string | null>(null); // base64 audio
  const lastResponseTextRef = useRef<string | null>(null);
  const resumeTimeoutRef = useRef<number | null>(null);

  // Initialize Web Speech API
  useEffect(() => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      console.warn("Speech Recognition not supported in this browser");
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    const safeStart = () => {
      try {
        recognition.start();
      } catch (e) {
        // If already started, try again after a short delay
        if (recognitionRestartTimeout.current) clearTimeout(recognitionRestartTimeout.current);
        recognitionRestartTimeout.current = setTimeout(() => {
          try { recognition.start(); } catch {}
        }, 500);
      }
    };

    recognition.onend = () => {
      if (recognitionRestartTimeout.current) clearTimeout(recognitionRestartTimeout.current);
      recognitionRestartTimeout.current = setTimeout(() => {
        safeStart();
      }, 500);
    };
    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      // Suppress 'aborted' errors
      if (event.error === 'aborted') return;
      console.warn('Speech recognition error:', event.error);
      if (recognitionRestartTimeout.current) clearTimeout(recognitionRestartTimeout.current);
      recognitionRestartTimeout.current = setTimeout(() => {
        safeStart();
      }, 500);
    };
    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const last = event.results[event.results.length - 1];
      const text = last[0].transcript.trim().toLowerCase();
      if (text === 'pause' || text === 'stop') {
        socketRef.current?.emit('audio_chunk', { 
          audio: '',  // Empty audio data
          isCommand: true,
          command: text
        });
      }
    };

    safeStart();
    recognitionRef.current = recognition;

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
      if (recognitionRestartTimeout.current) clearTimeout(recognitionRestartTimeout.current);
    };
  }, []);

  // Helper to convert blob to base64 and send to backend
  const sendAudioChunk = useCallback((blob: Blob) => {
    const reader = new FileReader();
    reader.onloadend = () => {
      const base64Audio = (reader.result as string).split(',')[1];
      socketRef.current?.emit('audio_chunk', { audio: base64Audio });
    };
    reader.readAsDataURL(blob);
  }, []);

  // Voice activity detection using Web Audio API
  const monitorVoiceActivity = useCallback(() => {
    if (!audioContextRef.current || !analyserRef.current) return;
    const analyser = analyserRef.current;
    const dataArray = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(dataArray);
    
    // Calculate RMS (root mean square) volume
    let sumSquares = 0;
    for (let i = 0; i < dataArray.length; i++) {
      const normalized = (dataArray[i] - 128) / 128;
      sumSquares += normalized * normalized;
    }
    const rms = Math.sqrt(sumSquares / dataArray.length);

    // Update voice activity state
    if (rms > VOICE_THRESHOLD) {
      setHasVoiceActivity(true);
      if (voiceActivityTimeoutRef.current) {
        clearTimeout(voiceActivityTimeoutRef.current);
      }
      voiceActivityTimeoutRef.current = setTimeout(() => {
        setHasVoiceActivity(false);
      }, 500); // Small delay to prevent flickering
    }

    // Check for silence
    if (rms < SILENCE_THRESHOLD) {
      if (!silenceTimerRef.current) {
        silenceTimerRef.current = setTimeout(() => {
          stopListening();
        }, SILENCE_DURATION);
      }
    } else {
      if (silenceTimerRef.current) {
        clearTimeout(silenceTimerRef.current);
        silenceTimerRef.current = null;
      }
    }
    animationFrameRef.current = requestAnimationFrame(monitorVoiceActivity);
  }, []);

  // Stop listening (including from silence or manual stop)
  const stopListening = useCallback(() => {
    if (mediaRecorderRef.current && isListening) {
      mediaRecorderRef.current.stop();
      setIsListening(false);
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
    if (voiceActivityTimeoutRef.current) {
      clearTimeout(voiceActivityTimeoutRef.current);
      voiceActivityTimeoutRef.current = null;
    }
    setHasVoiceActivity(false);
    // Show buffered response if any
    if (botResponseBuffer.current.trim()) {
      setMessages(prev => [...prev, botResponseBuffer.current.trim()]);
      botResponseBuffer.current = '';
    }
    if (resumeTimeoutRef.current) clearTimeout(resumeTimeoutRef.current);
  }, [isListening]);

  // Start hands-free listening
  const startListening = useCallback(async () => {
    setIsPaused(false);
    setIsListening(true);
    setIsLoading(true);
    setConnectionError(false);

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;
    const recorder = new MediaRecorder(stream);
    mediaRecorderRef.current = recorder;
    chunksRef.current = [];

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    recorder.onstop = () => {
      setIsListening(false);
      stream.getTracks().forEach(t => t.stop());
      const audioBlob = new Blob(chunksRef.current, { type: 'audio/wav' });
      sendAudioChunk(audioBlob);
      chunksRef.current = [];
      if (audioContextRef.current) {
        audioContextRef.current.close();
        audioContextRef.current = null;
      }
      if (animationFrameRef.current) {
        cancelAnimationFrame(animationFrameRef.current);
        animationFrameRef.current = null;
      }
    };

    audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
    const source = audioContextRef.current.createMediaStreamSource(stream);
    analyserRef.current = audioContextRef.current.createAnalyser();
    analyserRef.current.fftSize = 2048;
    source.connect(analyserRef.current);
    monitorVoiceActivity();

    recorder.start();
  }, [monitorVoiceActivity, sendAudioChunk, stopListening]);

  useEffect(() => {
    // Use the same origin in production, or localhost in development
    const backendUrl =
      process.env.NODE_ENV === 'production'
        ? window.location.origin
        : 'http://localhost:5000';

    socketRef.current = io(backendUrl, {
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
      timeout: 20000,
      forceNew: true
    });

    socketRef.current.on('connect_error', (error) => {
      console.error('Socket connection error:', error);
      setConnectionError(true);
    });

    socketRef.current.on('connect', () => {
      console.log('Socket connected successfully');
      setConnectionError(false);
    });

    socketRef.current.on('pause', (data: { message: string }) => {
      setIsPaused(true);
      setHasVoiceActivity(false);
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.currentTime = 0;
      }
      // On pause, also display the full response buffer if any
      if (botResponseBuffer.current.trim() !== '') {
        setMessages(prev => [...prev, botResponseBuffer.current.trim()]);
        botResponseBuffer.current = '';
      }
      setMessages(prev => [...prev, data.message]);
      // Always start listening for the next user input (hands-free), even if already listening
      startListening();
    });

    // Streaming text chunks: buffer only, do not update messages
    socketRef.current.on('response_chunk', (data: { text: string }) => {
      botResponseBuffer.current += data.text;
    });

    // Final audio + text: show full response as a new block
    socketRef.current.on('audio_response', (data: { audio: string }) => {
      setHasVoiceActivity(true);
      setIsLoading(false);
      if (audioRef.current) {
        audioRef.current.pause();
        audioRef.current.currentTime = 0;
      }
      const bufferText = botResponseBuffer.current.trim();
      console.log('audio_response: buffer =', bufferText);
      if (bufferText) {
        setMessages(prev => {
          const newMessages = [...prev, bufferText];
          console.log('setMessages: newMessages =', newMessages);
          return newMessages;
        });
        lastResponseTextRef.current = bufferText;
        botResponseBuffer.current = '';
      }
      lastTTSRef.current = data.audio;
      const audio = new Audio(`data:audio/mp3;base64,${data.audio}`);
      audioRef.current = audio;
      audio.play();
      audio.onended = () => {
        setHasVoiceActivity(false);
        startListening();
      };
    });

    socketRef.current.on('error', (data: { message: string }) => {
      setIsPaused(false);
      setHasVoiceActivity(false);
      setIsLoading(false);
      setConnectionError(true);
    });

    return () => {
      socketRef.current?.disconnect();
      if (audioContextRef.current) audioContextRef.current.close();
      if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
      if (voiceActivityTimeoutRef.current) clearTimeout(voiceActivityTimeoutRef.current);
    };
  }, [isListening, startListening, stopListening]);

  console.log('Pause button render: isListening:', isListening, 'isPaused:', isPaused);
  console.log('RENDER: messages =', messages);

  return (
    <div className="App">
      <header className="App-header">
        <h1>Guide Bot <span role="img" aria-label="robot">🤖</span></h1>
        <p>Ask me anything about Indian tourism!</p>
      </header>
      <main className="chat-container">
        <div className="bouncing-circle-container">
          <div className={`bouncing-circle${hasVoiceActivity ? ' active' : ''}`}></div>
        </div>
        {/* WhatsApp-like chat area */}
        <div className="chat-box" style={{ flex: 1, minHeight: 220, maxHeight: 340, width: '100%', background: '#ece5dd', borderRadius: 10, boxShadow: '0 1px 2px #0001', margin: '16px 0 0 0', padding: '12px 8px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
          {messages.map((msg, i) => (
            <div
              key={i}
              className="message-bubble"
              style={{
                background: '#fff',
                borderRadius: 8,
                padding: '10px 14px',
                color: '#222',
                fontSize: 15,
                maxWidth: '85%',
                alignSelf: 'flex-start',
                boxShadow: '0 1px 1.5px #0001',
                marginBottom: 0,
                whiteSpace: 'pre-line',
                wordBreak: 'break-word',
                border: '1px solid #e0e0e0',
              }}
            >
              {msg}
            </div>
          ))}
        </div>
        {isLoading && <div className="loading-indicator">Loading...</div>}
        {connectionError && <div className="error-indicator">Connection error. Please check your backend.</div>}
        <div className="controls">
          <button
            className={`record-button ${isListening ? 'recording' : ''}`}
            onClick={isListening ? stopListening : startListening}
            disabled={isPaused}
          >
            {isListening ? 'Listening... (Click to Stop)' : 'Start Listening'}
          </button>
          <div style={{ marginTop: 12 }}>
            <button
              className="pause-stop-button"
              style={{ backgroundColor: '#e57373', color: 'white', padding: '6px 16px', border: 'none', borderRadius: 4, fontSize: 14, cursor: 'pointer', boxShadow: 'none', fontWeight: 500 }}
              onClick={() => {
                if (!isPaused) {
                  console.log('Pause button clicked');
                  stopListening();
                  if (audioRef.current) {
                    audioRef.current.pause();
                    audioRef.current.currentTime = 0;
                  }
                  if (botResponseBuffer.current.trim()) {
                    setMessages(prev => [...prev, botResponseBuffer.current.trim()]);
                    botResponseBuffer.current = '';
                  }
                  setIsPaused(true);
                  console.log('Paused: isPaused set to true');
                  // Clear any resume timer
                  if (resumeTimeoutRef.current) clearTimeout(resumeTimeoutRef.current);
                } else {
                  console.log('Resume button clicked');
                  setIsPaused(false);
                  startListening();
                  console.log('Resumed: isPaused set to false, listening started');
                  // Start 20s timer to replay last TTS if no speech
                  if (resumeTimeoutRef.current) clearTimeout(resumeTimeoutRef.current);
                  resumeTimeoutRef.current = window.setTimeout(() => {
                    if (lastTTSRef.current && lastResponseTextRef.current) {
                      setMessages(prev => [...prev, lastResponseTextRef.current!]);
                      const audio = new Audio(`data:audio/mp3;base64,${lastTTSRef.current}`);
                      audioRef.current = audio;
                      audio.play();
                    }
                  }, 20000);
                }
              }}
              disabled={false} // Always enabled for debugging
            >
              {isPaused ? '▶️ Resume' : '⏸ Pause'}
            </button>
          </div>
        </div>
      </main>
    </div>
  );
};

export default App; 